"""Settings: consent, data location/retention/export/delete, camera device, model, calibration."""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.recorder import RecorderState
from focuslab.config import MODE_PROFILES, RULE_VERSION, RuleConfig, face_model_path
from focuslab.model_fetch import FACE_MODEL_URL, fetch_face_model
from focuslab.services.export_service import delete_all, export_csv, export_json
from focuslab.ui.calibration_dialog import CalibrationDialog
from focuslab.ui.consent import (
    ask_activity_consent,
    ask_camera_consent,
    ask_recording_consent,
)
from focuslab.ui.context import AppContext

COLLECTED = (
    "<b>저장하는 것</b>: 세션 목표·모드·시간, 1초 단위 추정 상태와 근거 코드,"
    " 맨 앞 앱의 프로세스 이름, (자동 기록 동의 시) 프로그램별 사용 구간과 제품 이름,"
    " 사용자가 입력한 정정·자기보고, 설정값.<br>"
    "<b>저장하지 않는 것</b>: 카메라 영상·사진, 얼굴 좌표, 음성, 키 입력 내용,"
    " 창 제목, 실행 파일 경로, URL, 스크린샷.<br>"
    "모든 데이터는 이 PC에만 있으며 FocusLab은 서버로 아무것도 보내지 않습니다."
)


class _Signals(QObject):
    modelFetched = Signal(str)


def camera_names() -> list[str]:
    try:
        from PySide6.QtMultimedia import QMediaDevices

        return [d.description() for d in QMediaDevices.videoInputs()]
    except Exception:  # QtMultimedia backend missing: fall back to indices
        return []


class SettingsPage(QWidget):
    dataChanged = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._signals = _Signals()
        self._signals.modelFetched.connect(self._model_fetched)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(QLabel("설정", objectName="PageTitle"))
        root.addWidget(self._privacy_box())
        root.addWidget(self._camera_box())
        root.addWidget(self._rules_box())
        root.addStretch()
        self.refresh()

    # sections ---------------------------------------------------------------------
    def _privacy_box(self) -> QGroupBox:
        box = QGroupBox("개인정보와 데이터")
        form = QFormLayout(box)
        info = QLabel(COLLECTED, wordWrap=True)
        info.setStyleSheet("font-weight:400;")
        form.addRow(info)

        self.recording_state = QLabel(wordWrap=True)
        self.recording_button = QPushButton()
        self.recording_button.clicked.connect(self._toggle_recording)
        form.addRow("자동 활동 기록", _row(self.recording_state, self.recording_button))

        self.activity_state = QLabel()
        self.activity_button = QPushButton()
        self.activity_button.clicked.connect(self._toggle_activity)
        form.addRow("PC 활동 관찰", _row(self.activity_state, self.activity_button))
        self.camera_state = QLabel()
        self.camera_button = QPushButton()
        self.camera_button.clicked.connect(self._toggle_camera)
        form.addRow("카메라 관찰", _row(self.camera_state, self.camera_button))

        path = QLabel(str(self.ctx.data_dir), wordWrap=True)
        open_dir = QPushButton("폴더 열기")
        open_dir.clicked.connect(self._open_data_dir)
        form.addRow("저장 위치", _row(path, open_dir))

        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSuffix(" 일")
        self.retention.setSpecialValueText("무제한")
        apply = QPushButton("적용")
        apply.clicked.connect(self._apply_retention)
        form.addRow("보존 기간", _row(self.retention, apply))

        exp_json = QPushButton("전체 JSON 내보내기")
        exp_json.clicked.connect(lambda: self._export_all("json"))
        exp_csv = QPushButton("전체 CSV 내보내기")
        exp_csv.clicked.connect(lambda: self._export_all("csv"))
        self.delete_all_button = QPushButton("모든 기록 삭제", objectName="Danger")
        self.delete_all_button.clicked.connect(self._delete_all)
        form.addRow("내보내기·삭제", _row(exp_json, exp_csv, self.delete_all_button))
        return box

    def _camera_box(self) -> QGroupBox:
        box = QGroupBox("카메라")
        form = QFormLayout(box)
        self.device = QComboBox()
        self.device.currentIndexChanged.connect(self._device_changed)
        form.addRow("장치", self.device)
        self.model_state = QLabel(wordWrap=True)
        self.model_button = QPushButton("얼굴 모델 받기")
        self.model_button.clicked.connect(self._fetch_model)
        form.addRow("얼굴 모델", _row(self.model_state, self.model_button))
        self.calib_state = QLabel(wordWrap=True)
        self.calib_button = QPushButton("보정 시작")
        self.calib_button.clicked.connect(self._calibrate)
        reset = QPushButton("초기화")
        reset.clicked.connect(self._reset_calibration)
        form.addRow("머리 방향 보정", _row(self.calib_state, self.calib_button, reset))
        return box

    def _rules_box(self) -> QGroupBox:
        cfg = RuleConfig()
        box = QGroupBox(f"판정 규칙 ({RULE_VERSION}, 튜닝 전 가설)")
        layout = QVBoxLayout(box)
        modes = ", ".join(
            f"{m.value} 자리 비움 {p.away_face_absent_s:.0f}초/화면 외 {p.head_away_s:.0f}초"
            for m, p in MODE_PROFILES.items()
        )
        text = (
            f"• 허용 목록에 없는 앱 {cfg.unrelated_app_s:.0f}초 이상 → 이탈 의심<br>"
            f"• 얼굴 없음 + 입력 없음 {cfg.away_idle_s:.0f}초 이상 → 자리 비움(추정)<br>"
            f"• 화면 외 방향 + 입력 없음 {cfg.head_away_idle_s:.0f}초 이상 → 이탈 의심 "
            "(아래쪽 시선만으로는 판정하지 않음)<br>"
            f"• 카메라 관찰값 {cfg.face_ttl_ms / 1000:.0f}초, PC 관찰값 "
            f"{cfg.activity_ttl_ms / 1000:.0f}초가 지나면 판단 불가<br>"
            f"• 작업 관련·판단 불가로 바뀌려면 {cfg.enter_dwell_s:.0f}초 유지 필요"
            " (깜박임 방지)<br>"
            f"• 모드별: {modes}"
        )
        label = QLabel(text, wordWrap=True)
        label.setStyleSheet("font-weight:400;")
        layout.addWidget(label)
        return box

    # refresh ----------------------------------------------------------------------
    def refresh(self) -> None:
        self._refresh_recording()
        activity = self.ctx.activity_consent
        consent_text = {None: "아직 묻지 않음", True: "동의함", False: "동의 안 함"}
        self.activity_state.setText(consent_text[activity])
        self.activity_button.setText("철회" if activity else "동의")
        camera = self.ctx.camera_consent
        self.camera_state.setText("동의함" if camera else "동의 안 함")
        self.camera_button.setText("철회" if camera else "동의")
        self.retention.setValue(self.ctx.retention_days)

        self.device.blockSignals(True)
        self.device.clear()
        names = camera_names() or ["카메라 0"]
        for i, name in enumerate(names):
            self.device.addItem(f"{i}: {name}")
        self.device.setCurrentIndex(min(self.ctx.camera_index, len(names) - 1))
        self.device.blockSignals(False)

        model = face_model_path()
        self.model_state.setText(
            f"설치됨: {model}" if model else "없음 — 카메라 없이 PC 활동만 사용"
        )
        self.model_button.setVisible(model is None)
        calib = self.ctx.calibration()
        if calib.calibrated:
            self.calib_state.setText(
                f"보정됨 · 좌우 허용 ±{calib.yaw_limit:.0f}°, 아래 {calib.down_limit:.0f}°"
            )
        else:
            self.calib_state.setText("기본값 사용 (좌우 ±25°, 아래 20°)")
        if not self.ctx.camera_consent:
            self.calib_state.setText(self.calib_state.text() + " · 카메라 동의 후 보정 가능")
        self.calib_button.setEnabled(model is not None and self.ctx.camera_consent)

    def _refresh_recording(self) -> None:
        recorder = self.ctx.recorder
        status = recorder.status() if recorder else None
        if not self.ctx.recording_consent:
            text = "꺼짐 (동의 안 함)"
        elif status is None or status.state is RecorderState.STOPPED:
            text = "동의함 · 기록 중지됨" if not self.ctx.demo else "데모 모드에서는 기록하지 않음"
        elif status.state is RecorderState.PAUSED:
            text = "일시정지됨"
        else:
            current = status.current
            name = (current.display_name or current.exe_name) if current else None
            text = "기록 중" + (f" · 현재: {name}" if name else "")
        self.recording_state.setText(text)
        self.recording_button.setText("끄기" if self.ctx.recording_consent else "켜기")
        self.recording_button.setEnabled(not self.ctx.demo)

    def set_session_active(self, active: bool) -> None:
        self.calib_button.setEnabled(
            not active and face_model_path() is not None and self.ctx.camera_consent
        )
        self.delete_all_button.setEnabled(not active)

    # actions ----------------------------------------------------------------------
    def _toggle_recording(self) -> None:
        if self.ctx.recording_consent:
            self.ctx.set_flag("consent.recording", False)
            self.ctx.stop_recording()
        elif ask_recording_consent(self):
            self.ctx.set_flag("consent.recording", True)
            self.ctx.start_recording()
        self.refresh()

    def _toggle_activity(self) -> None:
        if self.ctx.activity_consent:
            self.ctx.set_flag("consent.activity", False)
        else:
            self.ctx.set_flag("consent.activity", ask_activity_consent(self))
        self.refresh()

    def _toggle_camera(self) -> None:
        if self.ctx.camera_consent:
            self.ctx.set_flag("consent.camera", False)
            self.ctx.set_flag("last.camera", False)
        else:
            self.ctx.set_flag("consent.camera", ask_camera_consent(self))
        self.refresh()
        self.dataChanged.emit()

    def _device_changed(self, index: int) -> None:
        if index >= 0:
            self.ctx.set_setting("camera.index", str(index))

    def _open_data_dir(self) -> None:
        self.ctx.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.data_dir)))

    def _apply_retention(self) -> None:
        days = self.retention.value()
        self.ctx.set_setting("privacy.retention_days", str(days))
        with self.ctx.service.lock:
            removed = self.ctx.service.repository.purge_older_than(days)
        QMessageBox.information(self, "보존 기간", f"적용했습니다. 삭제된 오래된 세션: {removed}개")
        self.dataChanged.emit()

    def _export_all(self, kind: str) -> None:
        default = str(Path.home() / f"focuslab-export.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, "전체 내보내기", default, f"*.{kind}")
        if not path:
            return
        with self.ctx.service.lock:
            (export_json if kind == "json" else export_csv)(self.ctx.service.repository, Path(path))
        QMessageBox.information(self, "내보내기", f"저장했습니다:\n{path}")

    def _delete_all(self) -> None:
        answer = QMessageBox.warning(
            self, "모든 기록 삭제",
            "모든 세션, 상태 기록, 정정 내역을 영구 삭제합니다. 설정과 동의는 유지됩니다.\n"
            "되돌릴 수 없습니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self.ctx.service.lock:
            delete_all(self.ctx.service.repository)
        self.dataChanged.emit()
        QMessageBox.information(self, "삭제", "모든 기록을 삭제했습니다.")

    def _fetch_model(self) -> None:
        answer = QMessageBox.question(
            self, "얼굴 모델 받기",
            "MediaPipe 공식 저장소에서 얼굴 랜드마크 모델(약 3.7MB)을 받아"
            " SHA256을 확인합니다.\n\n"
            f"{FACE_MODEL_URL}\n\n이 다운로드 외에 FocusLab은 네트워크를 사용하지 않습니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.model_button.setEnabled(False)
        self.model_state.setText("받는 중…")

        def work() -> None:
            try:
                path = fetch_face_model()
                self._signals.modelFetched.emit(f"ok:{path}")
            except Exception as exc:  # network/checksum errors are shown to the user
                self._signals.modelFetched.emit(f"error:{exc}")

        threading.Thread(target=work, daemon=True).start()

    def _model_fetched(self, message: str) -> None:
        self.model_button.setEnabled(True)
        if message.startswith("error:"):
            QMessageBox.warning(self, "얼굴 모델", f"받지 못했습니다: {message[6:]}")
        self.refresh()

    def _calibrate(self) -> None:
        dialog = CalibrationDialog(self.ctx.camera_index, self)
        if dialog.exec() and dialog.result_calibration:
            self.ctx.set_setting("camera.calibration", dialog.result_calibration.to_json())
        self.refresh()

    def _reset_calibration(self) -> None:
        self.ctx.set_setting("camera.calibration", None)
        self.refresh()


def _row(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        layout.addWidget(w)
    layout.addStretch()
    return holder

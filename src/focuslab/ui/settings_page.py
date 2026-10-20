"""Settings: consent, data location/retention/export/delete, camera device, model, calibration."""

import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab import autostart
from focuslab.activity.recorder import RecorderState
from focuslab.browser import install as browser_install
from focuslab.config import (
    EXTENSION_DIR,
    MODE_PROFILES,
    RULE_VERSION,
    RuleConfig,
    face_model_path,
)
from focuslab.domain.activity import Category
from focuslab.model_fetch import FACE_MODEL_URL, fetch_face_model
from focuslab.services.export_service import (
    apply_retention,
    delete_all,
    export_activity_csv,
    export_csv,
    export_json,
)
from focuslab.ui.calibration_dialog import CalibrationDialog
from focuslab.ui.consent import (
    ask_activity_consent,
    ask_browser_consent,
    ask_camera_consent,
    ask_recording_consent,
)
from focuslab.ui.context import AppContext
from focuslab.ui.theme import CATEGORY_LABELS

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
        root.addWidget(self._browser_box())
        root.addWidget(self._classify_box())
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
        self.recording_pause = QPushButton()
        self.recording_pause.clicked.connect(self._toggle_recording_pause)
        form.addRow(
            "자동 활동 기록",
            _row(self.recording_state, self.recording_button, self.recording_pause),
        )
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 60)
        self.idle_minutes.setSuffix(" 분")
        self.idle_minutes.valueChanged.connect(self._idle_changed)
        idle_hint = QLabel(
            "이 시간 동안 입력이 없으면 마지막 입력 시각부터 유휴로 기록",
            objectName="Muted", wordWrap=True,
        )
        form.addRow("유휴 기준", _row(self.idle_minutes, idle_hint))
        self.autostart = QCheckBox("Windows 로그인 시 트레이로 자동 실행")
        self.autostart.toggled.connect(self._autostart_toggled)
        self.close_to_tray = QCheckBox("창을 닫아도 트레이에서 계속 기록")
        self.close_to_tray.toggled.connect(
            lambda on: self.ctx.set_flag("ui.close_to_tray", on)
        )
        form.addRow("백그라운드", _row(self.autostart, self.close_to_tray))

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
        exp_activity = QPushButton("활동 기록 CSV")
        exp_activity.clicked.connect(lambda: self._export_all("activity"))
        form.addRow(
            "내보내기·삭제", _row(exp_json, exp_csv, exp_activity, self.delete_all_button)
        )
        return box

    def _browser_box(self) -> QGroupBox:
        box = QGroupBox("브라우저 사이트 기록 (Chrome · Edge, 선택)")
        form = QFormLayout(box)
        self.browser_state = QLabel(wordWrap=True)
        self.browser_button = QPushButton()
        self.browser_button.clicked.connect(self._toggle_browser)
        form.addRow("동의", _row(self.browser_state, self.browser_button))
        self.host_state = QLabel(wordWrap=True)
        self.host_install = QPushButton("연결 설치")
        self.host_install.clicked.connect(self._install_host)
        self.host_remove = QPushButton("연결 제거")
        self.host_remove.clicked.connect(self._remove_host)
        form.addRow("본체 연결", _row(self.host_state, self.host_install, self.host_remove))
        open_ext = QPushButton("확장 프로그램 폴더 열기")
        open_ext.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(EXTENSION_DIR)))
        )
        guide = QLabel(
            "chrome://extensions 또는 edge://extensions → 개발자 모드 → '압축해제된 확장"
            " 프로그램 로드'에서 이 폴더를 선택하세요."
            " 확장이 없어도 프로그램 기록은 정상 동작합니다.",
            wordWrap=True, objectName="Muted",
        )
        form.addRow("확장 프로그램", _row(open_ext))
        form.addRow(guide)
        return box

    def _refresh_browser(self) -> None:
        consent = self.ctx.browser_consent
        last = self.ctx.browser_last_report_ms()
        seen = (
            f" · 마지막 수신 {datetime.fromtimestamp(last / 1000):%m/%d %H:%M:%S}"
            if last else " · 아직 수신 없음"
        )
        self.browser_state.setText(("동의함" + seen) if consent else "동의 안 함")
        self.browser_button.setText("철회" if consent else "동의")
        registered = browser_install.registered()
        names = [name.title() for name, ok in registered.items() if ok]
        self.host_state.setText(("연결됨: " + ", ".join(names)) if names else "설치 안 됨")
        windows = sys.platform == "win32" and not self.ctx.demo
        self.host_install.setEnabled(windows)
        self.host_remove.setEnabled(windows and bool(names))
        self.browser_button.setEnabled(not self.ctx.demo)

    def _toggle_browser(self) -> None:
        if self.ctx.browser_consent:
            self.ctx.set_browser_consent(False)
        elif ask_browser_consent(self):
            self.ctx.set_browser_consent(True)
            if not any(browser_install.registered().values()):
                self._install_host()
        self.refresh()

    def _install_host(self) -> None:
        try:
            browser_install.install(self.ctx.data_dir)
        except OSError as exc:
            QMessageBox.warning(self, "브라우저 연결", f"설치하지 못했습니다: {exc}")
        self.refresh()

    def _remove_host(self) -> None:
        browser_install.uninstall(self.ctx.data_dir)
        self.refresh()

    def _classify_box(self) -> QGroupBox:
        box = QGroupBox("활동 분류 규칙과 기록 제외")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(
            "활동 화면에서 구간을 정정할 때 '이 앱·사이트에 항상 적용'을 고르면 규칙이 생깁니다."
            " 정정은 선택 사항이며 기본 규칙만으로도 자동 분류됩니다.",
            wordWrap=True, objectName="Muted",
        ))
        self.rules = QListWidget()
        self.rules.setMaximumHeight(110)
        delete_rule = QPushButton("선택한 규칙 삭제")
        delete_rule.clicked.connect(self._delete_rule)
        layout.addWidget(QLabel("내 분류 규칙"))
        layout.addWidget(self.rules)
        layout.addWidget(_row(delete_rule))

        self.excluded_apps = QListWidget()
        self.excluded_sites = QListWidget()
        lists = QHBoxLayout()
        for title, widget, kind in (
            ("기록하지 않을 프로그램 (예: keepass.exe)", self.excluded_apps, "app"),
            ("기록하지 않을 사이트 (예: bank.com)", self.excluded_sites, "site"),
        ):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            widget.setMaximumHeight(100)
            col.addWidget(widget)
            add = QPushButton("추가…")
            add.clicked.connect(lambda _=False, k=kind: self._add_exclusion(k))
            remove = QPushButton("선택 삭제")
            remove.clicked.connect(lambda _=False, w=widget: self._remove_exclusion(w))
            col.addWidget(_row(add, remove))
            lists.addLayout(col)
        layout.addLayout(lists)
        layout.addWidget(QLabel(
            "제외한 항목은 이름 없이 '제외됨' 시간으로만 남고, 이미 저장된 기록은 바뀌지 않습니다.",
            wordWrap=True, objectName="Muted",
        ))
        return box

    def _refresh_classification(self) -> None:
        with self.ctx.activity_repo() as repo:
            rules = repo.rules()
            apps, sites = repo.exclusions()
        self.rules.clear()
        for row in rules:
            kind = "사이트" if row["match_type"] == "site" else "프로그램"
            item = QListWidgetItem(
                f"{kind} {row['pattern']} → {CATEGORY_LABELS[Category(row['category'])]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, (row["match_type"], row["pattern"]))
            self.rules.addItem(item)
        for widget, values in ((self.excluded_apps, apps), (self.excluded_sites, sites)):
            widget.clear()
            widget.addItems(sorted(values))

    def _delete_rule(self) -> None:
        for item in self.rules.selectedItems():
            self.ctx.delete_rule(*item.data(Qt.ItemDataRole.UserRole))
        self.refresh()

    def _current_exclusions(self) -> tuple[list[str], list[str]]:
        def values(w: QListWidget) -> list[str]:
            return [w.item(i).text() for i in range(w.count())]

        return values(self.excluded_apps), values(self.excluded_sites)

    def _add_exclusion(self, kind: str) -> None:
        label = "실행 파일 이름 (예: keepass.exe)" if kind == "app" else "사이트 (예: bank.com)"
        text, ok = QInputDialog.getText(self, "기록 제외 추가", label)
        value = text.strip().lower()
        if not ok or not value:
            return
        if kind == "site":
            value = value.split("://")[-1].split("/")[0].removeprefix("www.")
        apps, sites = self._current_exclusions()
        (apps if kind == "app" else sites).append(value)
        self.ctx.set_exclusions(apps, sites)
        self.refresh()

    def _remove_exclusion(self, widget: QListWidget) -> None:
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))
        self.ctx.set_exclusions(*self._current_exclusions())
        self.refresh()

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
        self._refresh_browser()
        self._refresh_classification()
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
        running = status is not None and status.state is not RecorderState.STOPPED
        self.recording_pause.setVisible(running)
        self.recording_pause.setText(
            "재개" if status and status.state is RecorderState.PAUSED else "일시정지"
        )
        for widget, value in (
            (self.idle_minutes, round(self.ctx.idle_threshold_s / 60)),
            (self.autostart, autostart.is_enabled()),
            (self.close_to_tray, self.ctx.close_to_tray),
        ):
            widget.blockSignals(True)
            (widget.setValue if isinstance(widget, QSpinBox) else widget.setChecked)(value)
            widget.blockSignals(False)
        self.autostart.setEnabled(not self.ctx.demo)

    def set_session_active(self, active: bool) -> None:
        self.calib_button.setEnabled(
            not active and face_model_path() is not None and self.ctx.camera_consent
        )
        self.delete_all_button.setEnabled(not active)

    # actions ----------------------------------------------------------------------
    def _toggle_recording_pause(self) -> None:
        self.ctx.set_recording_paused(self.ctx.recording_state is RecorderState.RUNNING)
        self.refresh()

    def _idle_changed(self, minutes: int) -> None:
        self.ctx.set_idle_threshold(minutes * 60)

    def _autostart_toggled(self, on: bool) -> None:
        try:
            self.ctx.set_autostart(on)
        except OSError as exc:
            QMessageBox.warning(self, "자동 실행", f"시작 프로그램을 바꾸지 못했습니다: {exc}")
        self.refresh()

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
            removed = apply_retention(self.ctx.service.repository, days)
        QMessageBox.information(
            self, "보존 기간",
            f"적용했습니다. 삭제된 오래된 세션: {removed}개 (같은 기간의 활동 기록도 삭제)",
        )
        self.dataChanged.emit()

    def _export_all(self, kind: str) -> None:
        name, suffix = {"json": ("focuslab-export", "json"), "csv": ("focuslab-export", "csv"),
                        "activity": ("focuslab-activity", "csv")}[kind]
        default = str(Path.home() / f"{name}.{suffix}")
        path, _ = QFileDialog.getSaveFileName(self, "전체 내보내기", default, f"*.{suffix}")
        if not path:
            return
        exporter = {"json": export_json, "csv": export_csv, "activity": export_activity_csv}[kind]
        with self.ctx.service.lock:
            exporter(self.ctx.service.repository, Path(path))
        QMessageBox.information(self, "내보내기", f"저장했습니다:\n{path}")

    def _delete_all(self) -> None:
        answer = QMessageBox.warning(
            self, "모든 기록 삭제",
            "모든 세션, 상태 기록, 자동 활동 기록, 정정 내역을 영구 삭제합니다."
            " 설정·동의·분류 규칙·제외 목록은 유지됩니다.\n"
            "되돌릴 수 없습니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        recorder = self.ctx.recorder
        running = recorder is not None and recorder.state is RecorderState.RUNNING
        if running:  # flush and drop the open span first so nothing points at deleted rows
            recorder.pause()
        with self.ctx.service.lock:
            delete_all(self.ctx.service.repository)
        if running:
            recorder.resume()
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

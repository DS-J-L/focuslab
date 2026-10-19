"""Live session: current estimate with reasons, camera status/preview, live timeline, controls."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from focuslab.config import MODE_LABELS
from focuslab.domain.models import CameraStatus, FocusState
from focuslab.focus.fusion import FaceEvidence
from focuslab.focus.metrics import format_duration
from focuslab.focus.reasons import Reason, describe
from focuslab.services.session_service import Lifecycle, LiveSnapshot
from focuslab.ui.context import AppContext
from focuslab.ui.theme import CAMERA_LABELS, CORRECTION_LABELS, SHORT_LABELS
from focuslab.ui.widgets import Legend, StateBadge, TimelineWidget, clock_text

FACE_TEXT = {
    FaceEvidence.FORWARD: "화면 방향",
    FaceEvidence.DOWN: "아래쪽",
    FaceEvidence.AWAY: "화면 외 방향",
    FaceEvidence.ABSENT: "얼굴 안 보임",
    FaceEvidence.UNKNOWN: "판단 불가",
    FaceEvidence.OFF: "카메라 사용 안 함",
}


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


class SessionPage(QWidget):
    finishRequested = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        self.title = QLabel("진행 중인 세션이 없습니다", objectName="PageTitle")
        self.subtitle = QLabel("홈에서 목표와 모드를 정하고 세션을 시작하세요.", objectName="Muted")
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)
        header.addLayout(title_col, 1)
        self.camera_flag = QLabel("", objectName="CameraOn")
        header.addWidget(self.camera_flag, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        time_row = QHBoxLayout()
        self.clock = QLabel("00:00", styleSheet="font-size:34px; font-weight:700;")
        self.remaining = QLabel("", objectName="Muted")
        time_row.addWidget(self.clock)
        time_row.addWidget(self.remaining, 0, Qt.AlignmentFlag.AlignBottom)
        time_row.addStretch()
        root.addLayout(time_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        root.addWidget(self.progress)

        grid = QGridLayout()
        grid.setSpacing(14)
        state_card, state_layout = _card()
        state_layout.addWidget(QLabel("현재 추정 상태", objectName="CardTitle"))
        self.badge = StateBadge()
        state_layout.addWidget(self.badge)
        self.reasons = QLabel("", wordWrap=True)
        self.reasons.setTextFormat(Qt.TextFormat.PlainText)
        state_layout.addWidget(self.reasons)
        self.confidence = QProgressBar()
        self.confidence.setRange(0, 100)
        self.confidence.setFormat("신뢰도 %p%")
        self.confidence.setTextVisible(True)
        self.confidence.setMaximumHeight(16)
        state_layout.addWidget(self.confidence)
        self.sensors = QLabel("", objectName="Muted", wordWrap=True)
        state_layout.addWidget(self.sensors)
        state_layout.addStretch()
        grid.addWidget(state_card, 0, 0)

        cam_card, cam_layout = _card()
        cam_title = QLabel("카메라 (메모리에서만 처리, 저장 안 함)", objectName="CardTitle")
        cam_layout.addWidget(cam_title)
        self.preview = QLabel("미리보기 없음", alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(320, 240)
        self.preview.setStyleSheet("background:#1F2430; color:#8C94A6; border-radius:8px;")
        cam_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        toggles = QHBoxLayout()
        self.show_preview = QCheckBox("미리보기")
        self.show_preview.setChecked(self.ctx.flag("camera.preview", True))
        self.show_preview.toggled.connect(self._preview_toggled)
        self.show_overlay = QCheckBox("랜드마크 표시")
        self.show_overlay.setChecked(self.ctx.flag("camera.overlay", False))
        self.show_overlay.toggled.connect(self._overlay_toggled)
        toggles.addWidget(self.show_preview)
        toggles.addWidget(self.show_overlay)
        toggles.addStretch()
        cam_layout.addLayout(toggles)
        self.camera_status = QLabel("", objectName="Muted", wordWrap=True)
        cam_layout.addWidget(self.camera_status)
        grid.addWidget(cam_card, 0, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        root.addLayout(grid)

        tl_card, tl_layout = _card()
        tl_layout.addWidget(QLabel("타임라인 (마우스를 올리면 근거 표시)", objectName="CardTitle"))
        self.timeline = TimelineWidget(40)
        tl_layout.addWidget(self.timeline)
        tl_layout.addWidget(Legend())
        self.totals = QLabel("", objectName="Muted")
        tl_layout.addWidget(self.totals)
        root.addWidget(tl_card)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("일시정지")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.break_button = QPushButton("휴식 시작")
        self.break_button.clicked.connect(self._toggle_break)
        self.correct_button = QToolButton()
        self.correct_button.setText("잘못된 판정 수정")
        self.correct_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.correct_button)
        for label, text in CORRECTION_LABELS.items():
            menu.addAction(text, lambda lab=label: self._correct(lab))
        self.correct_button.setMenu(menu)
        self.finish_button = QPushButton("세션 종료", objectName="Danger")
        self.finish_button.clicked.connect(self.finishRequested.emit)
        for b in (self.pause_button, self.break_button, self.correct_button):
            controls.addWidget(b)
        controls.addStretch()
        self.feedback = QLabel("", objectName="Muted")
        controls.addWidget(self.feedback)
        controls.addWidget(self.finish_button)
        root.addLayout(controls)
        root.addStretch()

        self._preview_timer = QTimer(self, interval=100)
        self._preview_timer.timeout.connect(self._update_preview)
        self._preview_timer.start()
        self._snapshot = LiveSnapshot()
        self.refresh(self._snapshot)

    # actions ----------------------------------------------------------------------
    def _toggle_pause(self) -> None:
        svc = self.ctx.service
        if self._snapshot.lifecycle is Lifecycle.RUNNING:
            svc.pause()
        elif self._snapshot.lifecycle is Lifecycle.PAUSED:
            svc.resume()
        self.refresh(svc.snapshot())

    def _toggle_break(self) -> None:
        if self._snapshot.lifecycle is Lifecycle.RUNNING:
            self.ctx.service.set_break(not self._snapshot.on_break)
            self.refresh(self.ctx.service.snapshot())

    def _correct(self, label: FocusState) -> None:
        if self.ctx.service.correct_current(label):
            self.feedback.setText(f"현재 구간을 '{CORRECTION_LABELS[label]}'(으)로 정정했습니다.")
        else:
            self.feedback.setText("정정할 구간이 아직 없습니다.")

    def _preview_toggled(self, on: bool) -> None:
        self.ctx.set_flag("camera.preview", on)
        src = self.ctx.service.face_source
        if src is not None and hasattr(src, "preview_enabled"):
            src.preview_enabled = on
        if not on:
            self.preview.clear()
            self.preview.setText("미리보기 꺼짐")

    def _overlay_toggled(self, on: bool) -> None:
        self.ctx.set_flag("camera.overlay", on)
        src = self.ctx.service.face_source
        if src is not None and hasattr(src, "overlay_enabled"):
            src.overlay_enabled = on

    def _update_preview(self) -> None:
        if not self.isVisible() or not self.show_preview.isChecked():
            return
        src = self.ctx.service.face_source
        frame = src.preview() if src is not None and hasattr(src, "preview") else None
        if frame is None:
            if self.preview.pixmap() is not None and not self.preview.pixmap().isNull():
                self.preview.clear()
            self.preview.setText("미리보기 없음")
            return
        h, w, _ = frame.shape
        image = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image))

    # refresh ----------------------------------------------------------------------
    def refresh(self, snap: LiveSnapshot) -> None:
        self._snapshot = snap
        active = snap.lifecycle in (Lifecycle.RUNNING, Lifecycle.PAUSED)
        for w in (self.pause_button, self.break_button, self.correct_button, self.finish_button):
            w.setEnabled(active)
        if snap.config is None:
            self.title.setText("진행 중인 세션이 없습니다")
            self.subtitle.setText("홈에서 목표와 모드를 정하고 세션을 시작하세요.")
            self.badge.set_state(None)
            self.timeline.set_segments(())
            return

        cfg = snap.config
        self.title.setText(cfg.goal)
        state_word = {
            Lifecycle.RUNNING: "관찰 중", Lifecycle.PAUSED: "일시정지됨 (관찰·카메라 중지)",
            Lifecycle.FINISHED: "종료됨", Lifecycle.IDLE: "",
        }[snap.lifecycle]
        self.subtitle.setText(f"{MODE_LABELS[cfg.mode]} 모드 · {state_word}")
        self.pause_button.setText("재개" if snap.lifecycle is Lifecycle.PAUSED else "일시정지")
        self.break_button.setText("휴식 종료" if snap.on_break else "휴식 시작")
        self.break_button.setEnabled(snap.lifecycle is Lifecycle.RUNNING)

        planned = cfg.planned_minutes * 60
        self.clock.setText(clock_text(snap.active_s))
        if planned:
            self.remaining.setText(
                f"  남은 시간 {clock_text(planned - snap.active_s)}"
                f" · 일시정지 {clock_text(snap.paused_s)}"
            )
            self.progress.setRange(0, planned)
            self.progress.setValue(min(planned, snap.active_s))
        else:
            self.remaining.setText(f"  제한 없음 · 일시정지 {clock_text(snap.paused_s)}")
            self.progress.setRange(0, 0 if snap.lifecycle is Lifecycle.RUNNING else 1)

        decision = snap.decision
        if decision is None:
            self.badge.set_state(None)
            self.reasons.setText("첫 관찰을 기다리는 중…")
            self.confidence.setValue(0)
        else:
            held = Reason.HYSTERESIS_HOLD in decision.reason_codes
            self.badge.set_state(decision.state, held)
            self.reasons.setText("\n".join(f"• {t}" for t in describe(decision.reason_codes)))
            self.confidence.setValue(round(decision.confidence * 100))

        idle = "-" if snap.idle_s is None else f"{snap.idle_s:.0f}초 전"
        face = FACE_TEXT.get(snap.face_evidence, "-") if snap.face_evidence else "-"
        app = snap.app_name or "-"
        if self.ctx.demo:
            app += " (데모 센서)"
        self.sensors.setText(f"포그라운드 앱: {app}\n마지막 입력: {idle}\n머리 방향: {face}")

        camera_on = snap.camera_status in (CameraStatus.RUNNING, CameraStatus.STARTING)
        flag = "● 데모 카메라 센서 (실제 카메라 꺼짐)" if self.ctx.demo else "● 카메라 사용 중"
        self.camera_flag.setText(flag if camera_on else "")
        if not cfg.camera_enabled:
            self.camera_status.setText("이 세션은 카메라 없이 PC 활동만 사용합니다.")
        else:
            self.camera_status.setText(CAMERA_LABELS[snap.camera_status])

        self.timeline.set_segments(snap.segments, max(planned, snap.active_s))
        parts = [
            f"{SHORT_LABELS[s]} {format_duration(snap.seconds.get(s, 0))}"
            for s in FocusState
            if snap.seconds.get(s)
        ]
        self.totals.setText(" · ".join(parts) or "아직 기록 없음")

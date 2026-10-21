"Live session: current estimate with reasons, camera status/preview, live timeline, controls."

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from focuslab.config import mode_label
from focuslab.domain.models import CameraStatus, FocusState
from focuslab.focus.fusion import FaceEvidence
from focuslab.focus.metrics import format_duration
from focuslab.focus.reasons import Reason, describe
from focuslab.i18n import LocalizedMapping, tr
from focuslab.relevance.explain import evidence, sentence
from focuslab.relevance.models import RelevanceLevel
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.context import AppContext
from focuslab.ui.theme import CAMERA_LABELS, CORRECTION_LABELS, SHORT_LABELS
from focuslab.ui.widgets import (
    Legend,
    StateBadge,
    TimelineWidget,
    clock_text,
    frame_pixmap,
    preview_label,
    timer_text,
)

FACE_TEXT = LocalizedMapping(
    {
        FaceEvidence.FORWARD: "Facing the screen",
        FaceEvidence.DOWN: "Looking down",
        FaceEvidence.AWAY: "Looking away",
        FaceEvidence.ABSENT: "Face not visible",
        FaceEvidence.UNKNOWN: "Cannot determine",
        FaceEvidence.OFF: "Camera not in use",
    }
)


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)
    return frame, layout


class SessionPage(QWidget):
    pauseRequested = Signal()
    finishRequested = Signal()
    cameraStopRequested = Signal()
    overlayRequested = Signal()
    timerModeChanged = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # The cards with the camera preview are taller than a small window: scroll, never squeeze.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(objectName="PageContent")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        self.title = QLabel(tr("No session in progress"), objectName="PageTitle")
        self.subtitle = QLabel(
            tr("Press + on Home to start a session."), objectName="Muted"
        )
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)
        header.addLayout(title_col, 1)
        self.camera_flag = QLabel("", objectName="CameraOn")
        header.addWidget(self.camera_flag, 0, Qt.AlignmentFlag.AlignTop)
        self.camera_stop = QPushButton(tr("Turn off camera"))
        self.camera_stop.setToolTip(
            tr("Release the camera immediately while keeping the session running.")
        )
        self.camera_stop.clicked.connect(self.cameraStopRequested)
        self.camera_stop.hide()
        header.addWidget(self.camera_stop, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        time_row = QHBoxLayout()
        # Clicking the clock switches between counting up and counting down (also in Settings).
        self.clock = QPushButton("00:00", objectName="Clock")
        self.clock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clock.clicked.connect(self._toggle_countdown)
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
        state_layout.addWidget(QLabel(tr("Current estimated state"), objectName="CardTitle"))
        self.badge = StateBadge()
        state_layout.addWidget(self.badge)
        self.reasons = QLabel("", wordWrap=True)
        self.reasons.setTextFormat(Qt.TextFormat.PlainText)
        state_layout.addWidget(self.reasons)
        self.confidence = QProgressBar()
        self.confidence.setRange(0, 100)
        self.confidence.setFormat(tr("Confidence %p%"))
        self.confidence.setTextVisible(True)
        self.confidence.setMaximumHeight(16)
        state_layout.addWidget(self.confidence)
        self.sensors = QLabel("", objectName="Muted", wordWrap=True)
        state_layout.addWidget(self.sensors)
        state_layout.addStretch()
        grid.addWidget(state_card, 0, 0)

        cam_card, cam_layout = _card()
        cam_title = QLabel(tr("Camera (memory only; never saved)"), objectName="CardTitle")
        cam_layout.addWidget(cam_title)
        self.preview = preview_label(tr("No preview"))
        cam_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        toggles = QHBoxLayout()
        self.show_preview = QCheckBox(tr("Preview"))
        self.show_preview.setChecked(self.ctx.flag("camera.preview", True))
        self.show_preview.toggled.connect(self._preview_toggled)
        self.show_overlay = QCheckBox(tr("Show landmarks"))
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

        rel_card, rel_layout = _card()
        rel_layout.addWidget(QLabel(tr("Task relevance"), objectName="CardTitle"))
        self.relevance_text = QLabel("", wordWrap=True)
        self.relevance_text.setTextFormat(Qt.TextFormat.PlainText)
        rel_layout.addWidget(self.relevance_text)
        self.relevance_evidence = QLabel("", objectName="Muted", wordWrap=True)
        self.relevance_evidence.setTextFormat(Qt.TextFormat.PlainText)
        rel_layout.addWidget(self.relevance_evidence)
        answers = QHBoxLayout()
        self.answer_buttons = {}
        for level, text in (
            (RelevanceLevel.RELATED, tr("Helps the task")),
            (RelevanceLevel.POSSIBLY_UNRELATED, tr("Not related")),
            (RelevanceLevel.UNCERTAIN, tr("Not sure")),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, lv=level: self._answer(lv))
            answers.addWidget(button)
            self.answer_buttons[level] = button
        self.remember_answer = QCheckBox(tr("Also use for similar goals"))
        self.remember_answer.setToolTip(
            tr("Saved as a rule (Settings → Task relevance AI) and used in later sessions.")
        )
        answers.addWidget(self.remember_answer)
        answers.addStretch()
        rel_layout.addLayout(answers)
        root.addWidget(rel_card)

        tl_card, tl_layout = _card()
        tl_layout.addWidget(QLabel(tr("Timeline (hover for evidence)"), objectName="CardTitle"))
        self.timeline = TimelineWidget(40)
        tl_layout.addWidget(self.timeline)
        tl_layout.addWidget(Legend())
        self.totals = QLabel("", objectName="Muted")
        tl_layout.addWidget(self.totals)
        root.addWidget(tl_card)

        controls = QHBoxLayout()
        self.pause_button = QPushButton(tr("Pause"))
        self.pause_button.clicked.connect(self.pauseRequested.emit)
        self.break_button = QPushButton(tr("Start break"))
        self.break_button.clicked.connect(self._toggle_break)
        self.correct_button = QToolButton()
        self.correct_button.setText(tr("Correct an estimate"))
        self.correct_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.correct_button)
        for label, text in CORRECTION_LABELS.items():
            menu.addAction(text, lambda lab=label: self._correct(lab))
        self.correct_button.setMenu(menu)
        self.overlay_button = QPushButton(tr("Show overlay"))
        self.overlay_button.setToolTip(tr("Show the session time on top of other programs."))
        self.overlay_button.clicked.connect(self.overlayRequested.emit)
        self.finish_button = QPushButton(tr("End session"), objectName="Danger")
        self.finish_button.clicked.connect(self.finishRequested.emit)
        for b in (self.pause_button, self.break_button, self.correct_button, self.overlay_button):
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
    def _toggle_countdown(self) -> None:
        if self._snapshot.config is not None and self._snapshot.config.planned_minutes:
            self.ctx.set_flag("ui.timer_countdown", not self.ctx.timer_countdown)
            self.timerModeChanged.emit()
            self.refresh(self._snapshot)

    def _toggle_break(self) -> None:
        if self._snapshot.lifecycle is Lifecycle.RUNNING:
            self.ctx.service.set_break(not self._snapshot.on_break)
            self.refresh(self.ctx.service.snapshot())

    def _correct(self, label: FocusState) -> None:
        if self.ctx.service.correct_current(label):
            self.feedback.setText(
                tr("Corrected the current interval to '{p0}'.", p0=CORRECTION_LABELS[label])
            )
        else:
            self.feedback.setText(tr("No interval to correct yet."))

    def _answer(self, level: RelevanceLevel) -> None:
        remember = self.remember_answer.isChecked()
        if self.ctx.service.answer_relevance(level, remember):
            self.feedback.setText(
                tr("Saved your answer; it now counts instead of the automatic estimate.")
            )
            self.remember_answer.setChecked(False)
        else:
            self.feedback.setText(tr("No activity to answer about yet."))
        self.refresh(self.ctx.service.snapshot())

    def _preview_toggled(self, on: bool) -> None:
        self.ctx.set_flag("camera.preview", on)
        src = self.ctx.service.face_source
        if src is not None and hasattr(src, "preview_enabled"):
            src.preview_enabled = on
        if not on:
            self.preview.clear()
            self.preview.setText(tr("Preview off"))

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
            self.preview.setText(tr("No preview"))
            return
        self.preview.setPixmap(frame_pixmap(frame))

    # refresh ----------------------------------------------------------------------
    def refresh(self, snap: LiveSnapshot) -> None:
        self._snapshot = snap
        active = snap.lifecycle in ACTIVE
        for w in (
            self.pause_button,
            self.break_button,
            self.correct_button,
            self.overlay_button,
            self.finish_button,
            *self.answer_buttons.values(),
            self.remember_answer,
        ):
            w.setEnabled(active)
        if not snap.relevance_subject:
            for w in (*self.answer_buttons.values(), self.remember_answer):
                w.setEnabled(False)
        if snap.config is None:
            self.title.setText(tr("No session in progress"))
            self.subtitle.setText(tr("Press + on Home to start a session."))
            self.badge.set_state(None)
            self.timeline.set_segments(())
            self.camera_stop.hide()
            self.relevance_text.setText(tr("No activity to compare with the goal yet."))
            self.relevance_evidence.setText("")
            return

        cfg = snap.config
        self.title.setText(cfg.goal)
        state_word = {
            Lifecycle.RUNNING: tr("Observing"),
            Lifecycle.PAUSED: tr("Paused (observation and camera stopped)"),
            Lifecycle.FINISHED: tr("Ended"),
            Lifecycle.IDLE: "",
        }[snap.lifecycle]
        label = mode_label(cfg.mode, cfg.mode_name)
        self.subtitle.setText(tr("{p0} mode · {p1}", p0=label, p1=state_word))
        self.pause_button.setText(
            tr("Resume") if snap.lifecycle is Lifecycle.PAUSED else tr("Pause")
        )
        self.break_button.setText(tr("End break") if snap.on_break else tr("Start break"))
        self.break_button.setEnabled(snap.lifecycle is Lifecycle.RUNNING)

        planned = cfg.planned_minutes * 60
        countdown = self.ctx.timer_countdown
        self.clock.setText(timer_text(snap.active_s, planned, countdown))
        if planned:
            self.clock.setToolTip(
                tr("Click to count up from 0") if countdown else tr("Click to show the time left")
            )
            # The clock shows one of elapsed / left; the line beside it gives the other.
            paused = clock_text(snap.paused_s)
            if countdown:
                other = tr("  Elapsed {p0} · Paused {p1}", p0=clock_text(snap.active_s), p1=paused)
            else:
                left = clock_text(planned - snap.active_s)
                other = tr("  Remaining {p0} · Paused {p1}", p0=left, p1=paused)
            self.remaining.setText(other)
            self.progress.setRange(0, planned)
            self.progress.setValue(min(planned, snap.active_s))
        else:
            self.clock.setToolTip("")
            self.remaining.setText(
                tr("  No time limit · Paused {p0}", p0=clock_text(snap.paused_s))
            )
            self.progress.setRange(0, 0 if snap.lifecycle is Lifecycle.RUNNING else 1)

        decision = snap.decision
        if decision is None:
            self.badge.set_state(None)
            self.reasons.setText(tr("Waiting for the first observation…"))
            self.confidence.setValue(0)
        else:
            held = Reason.HYSTERESIS_HOLD in decision.reason_codes
            self.badge.set_state(decision.state, held)
            self.reasons.setText("\n".join(f"• {t}" for t in describe(decision.reason_codes)))
            self.confidence.setValue(round(decision.confidence * 100))

        self.relevance_text.setText(sentence(snap.relevance, cfg.goal, snap.relevance_subject))
        self.relevance_evidence.setText(evidence(snap.relevance))

        idle = "-" if snap.idle_s is None else tr("{p0:.0f}s ago", p0=snap.idle_s)
        face = FACE_TEXT.get(snap.face_evidence, "-")
        app = snap.app_name or "-"
        if self.ctx.demo:
            app += tr(" (demo sensors)")
        self.sensors.setText(
            tr("Foreground app: {p0}\nLast input: {p1}\nHead pose: {p2}", p0=app, p1=idle, p2=face)
        )

        camera_on = snap.camera_status in (CameraStatus.RUNNING, CameraStatus.STARTING)
        flag = (
            tr("● Demo camera sensor (real camera off)") if self.ctx.demo else tr("● Camera in use")
        )
        self.camera_flag.setText(flag if camera_on else "")
        self.camera_stop.setVisible(camera_on and active)
        if not cfg.camera_enabled:
            self.camera_status.setText(tr("This session uses PC activity only, without a camera."))
        else:
            self.camera_status.setText(CAMERA_LABELS[snap.camera_status])

        self.timeline.set_segments(snap.segments, max(planned, snap.active_s))
        parts = [
            f"{SHORT_LABELS[s]} {format_duration(snap.seconds.get(s, 0))}"
            for s in FocusState
            if snap.seconds.get(s)
        ]
        self.totals.setText(" · ".join(parts) or tr("No records yet"))

"""Home: today's automatic recording and manual focus sessions side by side (each card says
which one it comes from), new session form (goal, mode, time, allowed apps, camera), recents."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.camera_overlay import session_samples
from focuslab.activity.stats import local_day_bounds
from focuslab.activity.windows_tracker import normalize, visible_window_apps
from focuslab.config import MODE_LABELS, NEUTRAL_APPS
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.focus.metrics import compute_metrics, format_duration, format_ratio
from focuslab.i18n import LocalizedMapping, tr
from focuslab.ui.context import AppContext
from focuslab.ui.recording_status import WARNING_STYLE, RecordingHealth
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.widgets import StatCard

MODE_HINTS = LocalizedMapping(
    {
        SessionMode.CODING: (
            "IDE, terminal, and documentation. Looking away alone does not establish task "
            "deviation."
        ),
        SessionMode.LECTURE: "Video lectures. No keyboard or mouse input is expected.",
        SessionMode.READING_WRITING: (
            "Paper books and notes. Looking down is treated as work, with a longer wait "
            "before estimating time away."
        ),
        SessionMode.CUSTOM: "Choose allowed apps yourself.",
    }
)
TODAY = "home.today"  # ActivityReporter key
AUTO, MANUAL = "Automatic recording", "Manual focus sessions"


class HomePage(QWidget):
    startRequested = Signal(object)  # SessionConfig
    openReport = Signal(int)
    openActivity = Signal()

    def __init__(self, ctx: AppContext, reporter: ActivityReporter) -> None:
        super().__init__()
        self.ctx = ctx
        self.reporter = reporter
        reporter.ready.connect(self._report_ready)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()  # two rows of cards and the form: scroll on small windows
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(objectName="PageContent")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Today"), objectName="PageTitle"))
        head.addStretch()
        self.recording_status = QLabel(objectName="Muted")
        head.addWidget(self.recording_status)
        self.to_activity = QPushButton(tr("View activity"))
        self.to_activity.clicked.connect(self.openActivity)
        head.addWidget(self.to_activity)
        root.addLayout(head)

        cards = QGridLayout()
        # Automatic recording: what the always-on recorder saw today, with or without a session.
        self.card_active = StatCard(
            tr("Input-based active time"),
            tr("0s"),
            tr("Time with keyboard or mouse input"),
            tag=AUTO,
        )
        self.card_work = StatCard(
            tr("Work-category time"),
            tr("0s"),
            tr("Time classified as development, study, documentation, etc."),
            tag=AUTO,
        )
        self.card_auto = StatCard(
            tr("Automatic sessions"),
            tr("0 sessions"),
            tr("Work intervals detected without a timer"),
            tag=AUTO,
        )
        for i, card in enumerate((self.card_active, self.card_work, self.card_auto)):
            cards.addWidget(card, 0, i)
        # Manual focus sessions: only the time inside sessions started here.
        self.card_sessions = StatCard(
            tr("Sessions"), "0", tr("Sessions with observations today"), tag=MANUAL
        )
        self.card_on = StatCard(
            tr("Estimated task-related time"),
            tr("0s"),
            tr("Does not prove actual attention"),
            tag=MANUAL,
        )
        self.card_off = StatCard(
            tr("Possibly off-task time"), tr("0s"), tr("Includes your corrections"), tag=MANUAL
        )
        self.card_cov = StatCard(
            tr("Observation coverage"),
            tr("Not measurable"),
            tr("Share excluding unknown states"),
            tag=MANUAL,
        )
        for i, card in enumerate((self.card_sessions, self.card_on, self.card_off, self.card_cov)):
            cards.addWidget(card, 1, i)
        root.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_form(), 3)
        recent_box = QGroupBox(tr("Recent sessions"))
        recent_layout = QVBoxLayout(recent_box)
        self.recent = QListWidget()
        self.recent.setWordWrap(True)
        self.recent.itemClicked.connect(self._open_recent)
        recent_layout.addWidget(self.recent)
        body.addWidget(recent_box, 2)
        root.addLayout(body, 1)

    def _open_recent(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is not None:
            self.openReport.emit(session_id)

    # form -------------------------------------------------------------------------
    def _build_form(self) -> QGroupBox:
        box = QGroupBox(tr("New session"))
        outer = QVBoxLayout(box)
        form = QFormLayout()
        outer.addLayout(form)
        outer.addStretch()
        form.setVerticalSpacing(10)
        self.goal = QLineEdit(self.ctx.setting("last.goal", "") or "")
        self.goal.setPlaceholderText(tr("For example: solve algorithm problems"))
        form.addRow(tr("Goal"), self.goal)

        self.mode = QComboBox()
        for mode in SessionMode:
            self.mode.addItem(MODE_LABELS[mode], mode)
        last_mode = self.ctx.setting("last.mode", SessionMode.CODING.value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(SessionMode(last_mode))))
        self.mode_hint = QLabel(objectName="Muted")
        self.mode_hint.setWordWrap(True)
        form.addRow(tr("Work mode"), self.mode)
        form.addRow("", self.mode_hint)

        self.minutes = QSpinBox()
        self.minutes.setRange(0, 240)
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(tr(" min"))
        self.minutes.setSpecialValueText(tr("No time limit"))
        self.minutes.setValue(int(self.ctx.setting("last.minutes", "25") or 25))
        form.addRow(tr("Target time"), self.minutes)

        self.apps = QListWidget()
        self.apps.setMinimumHeight(90)
        self.apps.setMaximumHeight(130)
        self.apps.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        app_buttons = QHBoxLayout()
        add = QPushButton(tr("Add manually…"))
        add.clicked.connect(self._add_app_manual)
        self.add_open = QPushButton(tr("Add from open apps…"))
        self.add_open.clicked.connect(self._add_app_from_open)
        remove = QPushButton(tr("Remove selected"))
        remove.clicked.connect(self._remove_apps)
        reset = QPushButton(tr("Defaults"))
        reset.clicked.connect(self._reset_apps)
        for b in (add, self.add_open, remove, reset):
            app_buttons.addWidget(b)
        app_buttons.addStretch()
        apps_col = QVBoxLayout()
        apps_col.addWidget(self.apps)
        apps_col.addLayout(app_buttons)
        note = QLabel(
            tr(
                "Matches process names (for example, code.exe). With the "
                "browser extension connected, add a site such as "
                "github.com to allow the browser only on that site."
            ),
            objectName="Muted",
        )
        note.setWordWrap(True)
        apps_col.addWidget(note)
        form.addRow(tr("Allowed apps"), apps_col)

        self.camera = QCheckBox(tr("Observe face presence and head pose with a webcam (optional)"))
        self.camera.setChecked(self.ctx.flag("last.camera", False))
        form.addRow(tr("Camera"), self.camera)

        self.start_button = QPushButton(tr("Start focus session"), objectName="Primary")
        self.start_button.clicked.connect(self._start)
        form.addRow("", self.start_button)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()
        return box

    def current_mode(self) -> SessionMode:
        return SessionMode(self.mode.currentData())

    def _mode_changed(self) -> None:
        mode = self.current_mode()
        self.mode_hint.setText(MODE_HINTS[mode])
        self._set_apps(self.ctx.allowed_apps(mode))

    def _set_apps(self, apps) -> None:
        self.apps.clear()
        for app in sorted(set(map(normalize, apps))):
            self.apps.addItem(app)

    def _current_apps(self) -> tuple[str, ...]:
        return tuple(self.apps.item(i).text() for i in range(self.apps.count()))

    def _save_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), self._current_apps())

    def _add(self, name: str) -> None:
        name = normalize(name)
        if name and name not in self._current_apps():
            self.apps.addItem(name)
            self.apps.sortItems()
            self._save_apps()

    def _add_app_manual(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("Add allowed app"), tr("Process name (for example, code.exe)")
        )
        if ok:
            self._add(name)

    def _add_app_from_open(self) -> None:
        menu = QMenu(self)
        names = [n for n in visible_window_apps() if normalize(n) not in NEUTRAL_APPS]
        for name in names:
            menu.addAction(name, lambda n=name: self._add(n))
        if not names:
            menu.addAction(tr("No open apps found")).setEnabled(False)
        menu.exec(self.add_open.mapToGlobal(self.add_open.rect().bottomLeft()))

    def _remove_apps(self) -> None:
        for item in self.apps.selectedItems():
            self.apps.takeItem(self.apps.row(item))
        self._save_apps()

    def _reset_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), None)
        self._set_apps(self.ctx.allowed_apps(self.current_mode()))

    def _start(self) -> None:
        apps = self._current_apps()
        if not apps:
            answer = QMessageBox.question(
                self,
                tr("No allowed apps"),
                tr("With an empty allow list, every app will be treated as not allowed. Continue?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        goal = self.goal.text().strip() or tr("Focus session")
        self.ctx.set_setting("last.goal", goal)
        self.ctx.set_setting("last.mode", self.current_mode().value)
        self.ctx.set_setting("last.minutes", str(self.minutes.value()))
        self.ctx.set_flag("last.camera", self.camera.isChecked())
        self.startRequested.emit(
            SessionConfig(
                goal, self.current_mode(), self.minutes.value(), apps, self.camera.isChecked()
            )
        )

    # summary ----------------------------------------------------------------------
    def refresh(self) -> None:
        today = datetime.now().astimezone().date()
        self.refresh_activity()
        with self.ctx.service.lock:
            repo = self.ctx.service.repository
            todays = session_samples(repo, *local_day_bounds(today))  # by each second's time
            sessions = repo.list_sessions(limit=12)
        metrics = compute_metrics([sample for _, _, sample in todays])
        self.card_sessions.set(str(len({sid for _, sid, _ in todays})))
        self.card_on.set(format_duration(metrics.seconds[FocusState.ON_TASK]))
        self.card_off.set(format_duration(metrics.seconds[FocusState.POSSIBLY_OFF_TASK]))
        self.card_cov.set(format_ratio(metrics.coverage))

        self.recent.clear()
        for s in sessions:
            started = datetime.fromisoformat(s.started_at_utc).astimezone()
            status = {"FINISHED": "", "INTERRUPTED": tr(" · Interrupted")}.get(
                s.status.value, tr(" · In progress")
            )
            item = QListWidgetItem(
                f"{started:%m/%d %H:%M}  {s.goal}  ({MODE_LABELS[s.mode]}){status}"
            )
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.recent.addItem(item)
        if not sessions:
            self.recent.addItem(tr("No sessions recorded yet."))

    def refresh_activity(self) -> None:
        "Today's automatic recording, computed on the report worker (never on this thread)."
        self.set_recording_health(self.ctx.recording_health())
        today = datetime.now().astimezone().date()
        self.reporter.request(TODAY, *local_day_bounds(today), today)

    def _report_ready(self, key: str, day, result) -> None:
        if key != TODAY:
            return
        st = result[1]
        self.card_active.set(format_duration(st.active_ms / 1000))
        self.card_work.set(format_duration(st.work_ms / 1000))
        self.card_auto.set(tr("{p0} sessions", p0=len(st.sessions)))

    def set_recording_health(self, health: RecordingHealth) -> None:
        self.recording_status.setText(health.text)
        self.recording_status.setStyleSheet(WARNING_STYLE if health.saving_failed else "")
        self.recording_status.setToolTip(health.detail)

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.start_button.setText(
            tr("Session in progress") if running else tr("Start focus session")
        )

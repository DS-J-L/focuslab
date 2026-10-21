"""Home: today's automatic recording and manual focus sessions side by side (each card says
which one it comes from), recent sessions, and a floating (+) button that opens the new
session bubble above it (or returns to the session in progress)."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QHideEvent, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.camera_overlay import session_samples
from focuslab.activity.stats import local_day_bounds
from focuslab.config import MODE_LABELS
from focuslab.domain.models import FocusState
from focuslab.focus.metrics import compute_metrics, format_duration, format_ratio
from focuslab.i18n import tr
from focuslab.ui.context import AppContext
from focuslab.ui.new_session_popover import NewSessionPopover
from focuslab.ui.recording_status import RecordingHealth
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.theme import set_style_flag
from focuslab.ui.widgets import StatCard

TODAY = "home.today"  # ActivityReporter key
# Card tags; translated where shown, since the language is chosen after import.
AUTO = "Automatic recording"
MANUAL = "Manual focus sessions"
FAB_SIZE = 56
FAB_MARGIN = 28


class HomePage(QWidget):
    newSessionRequested = Signal()
    sessionConfigured = Signal(object)  # SessionConfig, when Start is pressed in the bubble
    returnToSession = Signal()
    openReport = Signal(int)
    openActivity = Signal()

    def __init__(self, ctx: AppContext, reporter: ActivityReporter) -> None:
        super().__init__()
        self.ctx = ctx
        self.reporter = reporter
        reporter.ready.connect(self._report_ready)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()  # two rows of cards and the recents: scroll on small windows
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(objectName="PageContent")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, FAB_SIZE + FAB_MARGIN)  # clear of the (+)
        root.setSpacing(20)
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
        cards.setSpacing(12)
        # Automatic recording: what the always-on recorder saw today, with or without a session.
        self.card_active = StatCard(
            tr("Input-based active time"),
            tr("0s"),
            tr("Time with keyboard or mouse input"),
            tag=tr(AUTO),
        )
        self.card_work = StatCard(
            tr("Work-category time"),
            tr("0s"),
            tr("Time classified as development, study, documentation, etc."),
            tag=tr(AUTO),
        )
        self.card_auto = StatCard(
            tr("Automatic sessions"),
            tr("0 sessions"),
            tr("Work intervals detected without a timer"),
            tag=tr(AUTO),
        )
        for i, card in enumerate((self.card_active, self.card_work, self.card_auto)):
            cards.addWidget(card, 0, i * 4, 1, 4)
        # Manual focus sessions: only the time inside sessions started here.
        self.card_sessions = StatCard(
            tr("Sessions"), "0", tr("Sessions with observations today"), tag=tr(MANUAL)
        )
        self.card_on = StatCard(
            tr("Estimated task-related time"),
            tr("0s"),
            tr("Does not prove actual attention"),
            tag=tr(MANUAL),
        )
        self.card_off = StatCard(
            tr("Possibly off-task time"), tr("0s"), tr("Includes your corrections"), tag=tr(MANUAL)
        )
        self.card_cov = StatCard(
            tr("Observation coverage"),
            tr("Not measurable"),
            tr("Share excluding unknown states"),
            tag=tr(MANUAL),
        )
        for i, card in enumerate((self.card_sessions, self.card_on, self.card_off, self.card_cov)):
            cards.addWidget(card, 1, i * 3, 1, 3)
        for column in range(12):
            cards.setColumnStretch(column, 1)
        root.addLayout(cards)

        recent_box = QGroupBox(tr("Recent sessions"))
        recent_layout = QVBoxLayout(recent_box)
        self.recent = QListWidget()
        self.recent.setWordWrap(True)
        self.recent.setMinimumHeight(280)
        self.recent.itemClicked.connect(self._open_recent)
        recent_layout.addWidget(self.recent)
        root.addWidget(recent_box, 1)

        # Floats over the scroll area (a child of the page, not of the scrolled content), so it
        # stays in the bottom-right corner while the page scrolls.
        self.fab = QPushButton(self, objectName="Fab")
        self.fab.clicked.connect(self._fab_clicked)
        self.popover: NewSessionPopover | None = None
        self._running = False
        self.set_running(False)

    # floating button ------------------------------------------------------------------
    def set_running(self, running: bool) -> None:
        """Idle: a round (+) for a new session, or (×) while its bubble is open. In progress: a
        wide button back to that session."""
        self._running = running
        if running and self.popover is not None:
            self.popover.dismiss(animated=False)
        self.fab.setProperty("running", running)
        if running:
            self.fab.setText(tr("Back to session in progress"))
            self.fab.setToolTip("")
            self.fab.setAccessibleName(self.fab.text())
            self.fab.setMinimumWidth(0)
            self.fab.setMaximumWidth(16777215)
            self.fab.setFixedHeight(FAB_SIZE)
        else:
            label = tr("Close") if self.popover is not None else tr("New session")
            self.fab.setText("×" if self.popover is not None else "+")
            self.fab.setToolTip(label)
            self.fab.setAccessibleName(label)
            self.fab.setFixedSize(FAB_SIZE, FAB_SIZE)
        self.fab.style().unpolish(self.fab)
        self.fab.style().polish(self.fab)
        self._place_fab()

    def _fab_clicked(self) -> None:
        if self._running:
            self.returnToSession.emit()
        elif self.popover is not None:
            self.popover.dismiss()
        else:
            self.newSessionRequested.emit()

    def open_new_session(self) -> None:
        "Show the settings bubble above the (+), filled with the last session's choices."
        if self._running or self.popover is not None:
            return
        self.popover = NewSessionPopover(self.ctx, self.fab, self)
        self.popover.started.connect(self.sessionConfigured)
        self.popover.dismissed.connect(self._popover_dismissed)
        self.popover.open()
        self.set_running(False)

    def _popover_dismissed(self) -> None:
        self.popover = None
        self.set_running(self._running)

    def _place_fab(self) -> None:
        if self._running:
            self.fab.resize(self.fab.sizeHint().width(), FAB_SIZE)
        self.fab.move(
            self.width() - self.fab.width() - FAB_MARGIN,
            self.height() - self.fab.height() - FAB_MARGIN,
        )
        self.fab.raise_()
        if self.popover is not None:
            self.popover.place()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_fab()

    def hideEvent(self, event: QHideEvent) -> None:
        "Leaving Home (another menu, or the window to the tray) closes the bubble."
        super().hideEvent(event)
        if self.popover is not None:
            self.popover.dismiss(animated=False)

    def _open_recent(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is not None:
            self.openReport.emit(session_id)

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
            self.recent.addItem(
                tr("No sessions recorded yet. Start one with the + button at the bottom right.")
            )

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
        set_style_flag(self.recording_status, "warning", health.saving_failed)
        self.recording_status.setToolTip(health.detail)

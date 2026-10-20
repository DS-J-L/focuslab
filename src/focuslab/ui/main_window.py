"Main window: navigation, session start/finish flow, tray and application bootstrap."

import sys
from dataclasses import replace

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from focuslab import __version__
from focuslab.activity.recorder import RecorderState
from focuslab.config import data_dir, face_model_path
from focuslab.domain.models import SessionConfig
from focuslab.i18n import install_qt_translator, tr
from focuslab.services.export_service import apply_retention
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.activity_page import ActivityPage
from focuslab.ui.consent import ask_activity_consent, ask_camera_consent
from focuslab.ui.context import AppContext
from focuslab.ui.home_page import HomePage
from focuslab.ui.onboarding import OnboardingDialog
from focuslab.ui.report_page import ReportPage
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.session_page import SessionPage
from focuslab.ui.settings_page import SettingsPage
from focuslab.ui.theme import ACCENT, SELF_REPORT_LABELS, STYLESHEET
from focuslab.ui.tray import Tray, make_icon

HOME, ACTIVITY, SESSION, REPORT, SETTINGS = range(5)
ACTIVITY_REFRESH_MS = 30_000


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("FocusLab" + (tr(" (demo sensors)") if ctx.demo else ""))
        self.setWindowIcon(make_icon(ACCENT))
        self.resize(1180, 820)
        self.setMinimumSize(980, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        side.addWidget(QLabel("FocusLab", objectName="Brand"))
        tagline = QLabel("Know your workflow,\nnot just your screen time.", objectName="BrandSub")
        side.addWidget(tagline)
        self.nav = QListWidget()
        self.nav.addItems(
            [tr("Home"), tr("Activity"), tr("Sessions"), tr("Reports"), tr("Settings")]
        )
        side.addWidget(self.nav, 1)
        footer = QLabel(
            tr("v{p0} · Local only", p0=__version__)
            + (tr("\nDemo sensor mode") if ctx.demo else ""),
            objectName="BrandSub",
        )
        side.addWidget(footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        # Activity statistics run on a worker thread with its own database connection.
        self.reporter = ActivityReporter(ctx.db_path, self)
        self.home = HomePage(ctx, self.reporter)
        self.activity = ActivityPage(ctx, self.reporter)
        self.session = SessionPage(ctx)
        self.report = ReportPage(ctx)
        self.settings = SettingsPage(ctx)
        for page in (self.home, self.activity, self.session, self.report, self.settings):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._navigate)
        self.home.startRequested.connect(self.start_session)
        self.home.openReport.connect(self.open_report)
        self.home.openActivity.connect(lambda: self.go(ACTIVITY))
        self.session.pauseRequested.connect(self.toggle_pause)
        self.session.finishRequested.connect(self.finish_session)
        self.session.cameraStopRequested.connect(self.stop_camera)
        self.report.dataChanged.connect(self.home.refresh)
        self.settings.dataChanged.connect(self._data_changed)
        self.activity.dataChanged.connect(self.settings.refresh)

        self.tray = Tray(self)
        if Tray.isSystemTrayAvailable():
            self.tray.show()
        self._tray_hint_shown = False
        self._last_lifecycle = Lifecycle.IDLE

        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        # The home and activity pages follow the recorder while open (one day, on the worker).
        self._activity_timer = QTimer(self, interval=ACTIVITY_REFRESH_MS)
        self._activity_timer.timeout.connect(self._follow_recorder)
        self._activity_timer.start()
        self.nav.setCurrentRow(HOME)
        self.home.refresh()

    # navigation ---------------------------------------------------------------------
    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == HOME:
            self.home.refresh()
        elif index == ACTIVITY:
            self.activity.refresh()
        elif index == REPORT:
            self.report.refresh()
        elif index == SETTINGS:
            self.settings.refresh()
            self.settings.set_session_active(self._last_lifecycle in ACTIVE)

    def _follow_recorder(self) -> None:
        if self.stack.currentIndex() == ACTIVITY:
            self.activity.auto_refresh()
        elif self.stack.currentIndex() == HOME:
            self.home.refresh_activity()

    def go(self, index: int) -> None:
        self.nav.setCurrentRow(index)

    def open_report(self, session_id: int) -> None:
        self.go(REPORT)
        self.report.show_session(session_id)

    def _data_changed(self) -> None:
        self.home.refresh()
        self.report.refresh()
        if self.stack.currentIndex() == ACTIVITY:
            self.activity.refresh()

    def show_normal(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # session flow -------------------------------------------------------------------
    def start_session(self, config: SessionConfig) -> None:
        ctx = self.ctx
        if not ctx.demo and ctx.activity_consent is None:
            ctx.set_flag("consent.activity", ask_activity_consent(self))
        if config.camera_enabled and not ctx.demo:
            if not ctx.camera_consent:
                ctx.set_flag("consent.camera", ask_camera_consent(self))
            if not ctx.camera_consent:
                config = replace(config, camera_enabled=False)
            elif face_model_path() is None:
                QMessageBox.information(
                    self,
                    tr("Face model missing"),
                    tr(
                        "The face model is missing, so this session will use PC "
                        "activity only.\nDownload it in Settings > Camera."
                    ),
                )
                config = replace(config, camera_enabled=False)
        self.ctx.service.start(config)
        self.home.set_running(True)
        self.go(SESSION)
        self.poll()

    def toggle_pause(self) -> None:
        snap = self.ctx.service.snapshot()
        if snap.lifecycle is Lifecycle.RUNNING:
            self.ctx.service.pause()
        elif snap.lifecycle is Lifecycle.PAUSED:
            self.ctx.service.resume()
        self.poll()

    def finish_session(self) -> None:
        if self.ctx.service.snapshot().lifecycle not in ACTIVE:
            return
        answer = QMessageBox.question(
            self, tr("End session"), tr("End the session and view its report?")
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.ctx.service.finish()
            self.poll()

    def stop_camera(self) -> None:
        self.ctx.service.stop_camera()
        self.poll()

    def toggle_recording_pause(self) -> None:
        state = self.ctx.recording_state
        if state is not RecorderState.STOPPED:
            self.ctx.set_recording_paused(state is RecorderState.RUNNING)
        self.settings.refresh()
        self.poll()

    def poll(self) -> None:
        snap = self.ctx.service.snapshot()
        self.session.refresh(snap)
        health = self.ctx.recording_health()
        self.tray.update_state(snap, self.ctx.recording_state, health)
        if self.stack.currentIndex() == ACTIVITY:
            self.activity.set_recording_health(health)
        elif self.stack.currentIndex() == HOME:
            self.home.set_recording_health(health)
        if self._last_lifecycle in ACTIVE and snap.lifecycle is Lifecycle.FINISHED:
            self._last_lifecycle = snap.lifecycle
            self._on_finished(snap)
        self._last_lifecycle = snap.lifecycle

    def _on_finished(self, snap: LiveSnapshot) -> None:
        self.home.set_running(False)
        self.settings.set_session_active(False)
        if snap.planned_reached:
            self.show_normal()
            self.tray.showMessage(
                "FocusLab", tr("The target time was reached and the session has ended.")
            )
        self._ask_self_report(snap.session_id)
        self.home.refresh()
        self.open_report(snap.session_id)

    def _ask_self_report(self, session_id: int) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(tr("Session complete"))
        box.setText(tr("Did you achieve your goal? (Self-report; editable in Reports)"))
        buttons = {
            box.addButton(text, QMessageBox.ButtonRole.AcceptRole): key
            for key, text in SELF_REPORT_LABELS.items()
        }
        box.addButton(tr("Skip"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        value = buttons.get(box.clickedButton())
        if value:
            self.ctx.service.set_self_report(session_id, value)

    # closing ------------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        session = self.ctx.service.snapshot().lifecycle in ACTIVE
        recording = self.ctx.recording_state is not RecorderState.STOPPED
        if self.tray.isVisible() and (session or (recording and self.ctx.close_to_tray)):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(
                    "FocusLab",
                    tr(
                        "Recording continues in the tray. Click the icon to reopen "
                        "FocusLab, or use its menu to pause recording or quit."
                    ),
                )
                self._tray_hint_shown = True
            return
        event.ignore()
        self.quit_app()

    def quit_app(self) -> None:
        if self.ctx.service.snapshot().lifecycle in ACTIVE:
            self.show_normal()
            answer = QMessageBox.question(
                self, tr("Quit FocusLab"), tr("End the current session and quit FocusLab?")
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.close_down()
        QApplication.quit()

    def close_down(self) -> None:
        """Stop the UI timers first so no late tick touches the closed database, then the
        report worker, the recorder and the session service."""
        self._timer.stop()
        self._activity_timer.stop()
        self.reporter.shutdown()
        self.ctx.stop_recording()
        self.ctx.service.shutdown()
        self.tray.hide()


def _set_windows_app_id() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FocusLab.App")


def run_onboarding(ctx: AppContext, parent: QWidget | None = None) -> None:
    dialog = OnboardingDialog(parent, round(ctx.idle_threshold_s / 60))
    dialog.exec()
    ctx.apply_onboarding(dialog.choice())


def apply_theme(app: QApplication) -> None:
    """The stylesheet is a light design: keep Qt's palette light even in Windows dark mode,
    otherwise popups and unstyled areas get dark backgrounds under the dark stylesheet text."""
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setStyleSheet(STYLESHEET)


def run_app(demo: bool = False, background: bool = False) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FocusLab")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    if sys.platform == "win32":
        app.setFont(QFont("Malgun Gothic", 10))

    # One instance per data folder: a second one would mark the live session as interrupted.
    lock_path = data_dir() / "focuslab.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if background:  # sign-in start while FocusLab is already running: nothing to do
            return 0
        QMessageBox.information(
            None, "FocusLab", tr("FocusLab is already running. Check the tray icon.")
        )
        return 1

    ctx = AppContext(demo)
    install_qt_translator(app)
    recovered = ctx.service.recover_interrupted()
    with ctx.service.lock:
        apply_retention(ctx.service.repository, ctx.retention_days)
    if ctx.needs_onboarding:
        run_onboarding(ctx)
    ctx.start_recording()
    window = MainWindow(ctx)
    # Started at sign-in: stay in the tray (unless there is no tray to stay in).
    if not (background and window.tray.isVisible()):
        window.show()
    if recovered:
        QMessageBox.information(
            window,
            tr("Previous session recovered"),
            tr(
                (
                    "Saved {p0} uncleanly ended sessions as interrupted.\nYou "
                    "can view their records in Reports."
                ),
                p0=len(recovered),
            ),
        )
    code = app.exec()
    lock.unlock()
    return code

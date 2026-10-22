"Main window: navigation, session start/finish flow, tray and application bootstrap."

import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QLockFile, QRect, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFocusEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from focuslab import __version__, updater
from focuslab.activity.recorder import RecorderState
from focuslab.config import data_dir, face_model_path
from focuslab.domain.models import SessionConfig
from focuslab.focus.metrics import format_duration
from focuslab.i18n import install_qt_translator, tr
from focuslab.services.export_service import apply_retention
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.activity_page import ActivityPage
from focuslab.ui.consent import ask_activity_consent, ask_camera_consent
from focuslab.ui.context import AppContext
from focuslab.ui.guide import GuideTour, guide_steps
from focuslab.ui.home_page import HomePage
from focuslab.ui.onboarding import OnboardingDialog
from focuslab.ui.overlay import SessionOverlay
from focuslab.ui.report_page import ReportPage
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.session_page import SessionPage
from focuslab.ui.settings_page import SettingsPage
from focuslab.ui.theme import SELF_REPORT_LABELS, apply_theme
from focuslab.ui.tray import Tray, make_icon
from focuslab.ui.widgets import timer_text
from focuslab.ui.window_frame import (
    INTEGRATED_FRAME,
    TITLE_HEIGHT,
    TitleBar,
    WindowsFrame,
    native_frame_available,
)

HOME, ACTIVITY, SESSION, REPORT, SETTINGS = range(5)  # stack pages
# Sidebar rows. The live session has no row: it opens from Home's (+) and is reached again
# through the "session in progress" card under the menu.
NAV_PAGES = (HOME, ACTIVITY, REPORT, SETTINGS)
ACTIVITY_REFRESH_MS = 30_000
UPDATE_CHECK_DELAY_MS = 5_000


class NavList(QListWidget):
    def focusInEvent(self, event: QFocusEvent) -> None:
        """With no row selected (the live session is shown), Qt would select the first row on
        keyboard focus and so leave the session; focus alone must not navigate."""
        if self.currentRow() < 0:
            QFrame.focusInEvent(self, event)
            self.viewport().update()
        else:
            super().focusInEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        # The sidebar and the page run up to the top edge; the caption buttons sit on the page.
        self.title_bar: TitleBar | None = None
        self._frame: WindowsFrame | None = None
        if INTEGRATED_FRAME:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.title_bar = TitleBar()
        self.ctx = ctx
        self.setWindowTitle("FocusLab" + (tr(" (demo sensors)") if ctx.demo else ""))
        self.setWindowIcon(make_icon())
        self.resize(1180, 820)
        self.setMinimumSize(980, 680)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QWidget(objectName="Sidebar")
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        # With the integrated title bar, the brand still lines up with the page title.
        side.setContentsMargins(0, TITLE_HEIGHT if INTEGRATED_FRAME else 0, 0, 12)
        side.addWidget(QLabel("FocusLab", objectName="Brand"))
        tagline = QLabel(
            tr("Know your workflow,\nnot just your screen time."), objectName="BrandSub"
        )
        side.addWidget(tagline)
        self.nav = NavList()
        self.nav.addItems([tr("Home"), tr("Activity"), tr("Reports"), tr("Settings")])
        side.addWidget(self.nav, 1)
        self.session_return = QPushButton(objectName="SessionReturn")
        self.session_return.clicked.connect(lambda: self.go(SESSION))
        self.session_return.setVisible(False)
        return_row = QHBoxLayout()
        return_row.setContentsMargins(12, 0, 12, 8)
        return_row.addWidget(self.session_return)
        side.addLayout(return_row)
        self.update_button = QPushButton(objectName="Primary")
        self.update_button.clicked.connect(self._update_now)
        self.update_button.setVisible(False)
        update_row = QHBoxLayout()
        update_row.setContentsMargins(12, 0, 12, 8)
        update_row.addWidget(self.update_button)
        side.addLayout(update_row)
        footer = QLabel(
            tr("v{p0} · Local only", p0=__version__)
            + (tr("\nDemo sensor mode") if ctx.demo else ""),
            objectName="BrandSub",
        )
        side.addWidget(footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        # Activity statistics run on a worker thread with its own database connection.
        self.reporter = ActivityReporter(ctx.db_path, self, power=ctx.power_source())
        self.home = HomePage(ctx, self.reporter)
        self.activity = ActivityPage(ctx, self.reporter)
        self.session = SessionPage(ctx)
        self.report = ReportPage(ctx)
        self.settings = SettingsPage(ctx)
        for page in (self.home, self.activity, self.session, self.report, self.settings):
            self.stack.addWidget(page)
        if self.title_bar is None:
            layout.addWidget(self.stack, 1)
        else:
            page_column = QVBoxLayout()
            page_column.setContentsMargins(0, 0, 0, 0)
            page_column.setSpacing(0)
            page_column.addWidget(self.title_bar)
            page_column.addWidget(self.stack, 1)
            layout.addLayout(page_column, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._navigate)
        self.home.newSessionRequested.connect(self.new_session)
        self.home.sessionConfigured.connect(self.start_session)
        self.home.returnToSession.connect(lambda: self.go(SESSION))
        self.home.openReport.connect(self.open_report)
        self.home.openActivity.connect(lambda: self.go(ACTIVITY))
        self.session.pauseRequested.connect(self.toggle_pause)
        self.session.finishRequested.connect(self.finish_session)
        self.session.cameraStopRequested.connect(self.stop_camera)
        self.overlay = SessionOverlay(ctx)
        self.overlay.pauseRequested.connect(self.toggle_pause)
        self.overlay.finishRequested.connect(self.finish_session)
        self.overlay.breakRequested.connect(self.toggle_break)
        self.session.overlayRequested.connect(self.show_overlay)
        self.session.timerModeChanged.connect(self.poll)  # overlay, sidebar and tray at once
        self.report.dataChanged.connect(self.home.refresh)
        self.settings.dataChanged.connect(self._data_changed)
        self.activity.dataChanged.connect(self.settings.refresh)
        self.settings.updateAvailable.connect(self._show_update)
        self.settings.restartForUpdate.connect(self._restart_for_update)
        self.settings.overlayChanged.connect(self.overlay.apply_settings)
        self.settings.guideRequested.connect(self.show_guide)
        self.tour: GuideTour | None = None
        if ctx.flag("update.auto_check"):  # opt-in; off by default (local-only)
            QTimer.singleShot(
                UPDATE_CHECK_DELAY_MS, lambda: self.settings.check_updates(quiet=True)
            )

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
    def _navigate(self, row: int) -> None:
        if row < 0:  # cleared while the live session is shown
            return
        index = NAV_PAGES[row]
        self.stack.setCurrentIndex(index)
        self._mark_session_return()
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
        if index in NAV_PAGES:
            self.nav.setCurrentRow(NAV_PAGES.index(index))
            return
        # The session page has no menu row: clear the selection so any row navigates again.
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(-1)
        self.nav.blockSignals(False)
        self.stack.setCurrentIndex(index)
        self._mark_session_return()

    def open_report(self, session_id: int) -> None:
        self.go(REPORT)
        self.report.show_session(session_id)

    # guide --------------------------------------------------------------------------------
    def show_guide(self) -> None:
        "The tour over this window; skipping it still counts as seen. Ends on the page it began."
        if self.tour is not None:
            return
        self.ctx.set_flag("guide.done", True)
        start_page = self.stack.currentIndex()
        self.tour = GuideTour(self.centralWidget(), guide_steps(), self._guide_target)

        def finished(_completed: bool) -> None:
            self.tour = None
            self.go(start_page)

        self.tour.finished.connect(finished)
        self.tour.start()

    def _guide_target(self, target: str | None) -> QRect | None:
        "Bring a guide step's place on screen and return where it is, in global coordinates."
        if target in ("home", "new_session"):
            self.go(HOME)
            if target == "new_session":
                return _global_rect(self.home.fab)
            return _global_rect(self.home.card_active, self.home.card_cov)
        if target in ("activity", "reports"):
            item = self.nav.item(NAV_PAGES.index(ACTIVITY if target == "activity" else REPORT))
            rect = self.nav.visualItemRect(item)
            return QRect(self.nav.viewport().mapToGlobal(rect.topLeft()), rect.size())
        settings = {
            "work_modes": (self.settings.modes_box,),
            "recording": (
                self.settings.recording_state,
                self.settings.recording_button,
                self.settings.recording_pause,
            ),
            "guide": (self.settings.guide_button,),
        }.get(target or "")
        if settings is None:
            return None
        self.go(SETTINGS)
        for widget in reversed(settings):  # the first one ends up in view if not all fit
            if widget.isVisible():
                self.settings.scroll.ensureWidgetVisible(widget, 0, 60)
        return _global_rect(*settings)

    def _data_changed(self) -> None:
        self.home.refresh()
        self.report.refresh()
        if self.stack.currentIndex() == ACTIVITY:
            self.activity.refresh()

    # window frame -------------------------------------------------------------------
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self.title_bar is not None and self._frame is None and native_frame_available():
            self._frame = WindowsFrame(self, self.title_bar)

    def nativeEvent(self, event_type: QByteArray, message: int) -> tuple[bool, int]:
        if self._frame is not None:
            answer = self._frame.handle(int(message))
            if answer is not None:
                return answer
        return super().nativeEvent(event_type, message)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        changes = (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange)
        if self.title_bar is not None and event.type() in changes:
            self.title_bar.sync_state()
            if self._frame is not None:
                self._frame.sync_state()

    def show_normal(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # session flow -------------------------------------------------------------------
    def new_session(self) -> None:
        "Home's (+): open the settings bubble above it; its Start calls start_session."
        if self.ctx.service.snapshot().lifecycle in ACTIVE:
            self.go(SESSION)
            return
        self.go(HOME)
        self.home.open_new_session()

    def start_session(self, config: SessionConfig) -> None:
        ctx = self.ctx
        if ctx.service.snapshot().lifecycle in ACTIVE:  # one session at a time
            self.go(SESSION)
            return
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
        if ctx.overlay_on_start:
            self.show_overlay()
        self.poll()

    def show_overlay(self) -> None:
        self.overlay.start(self.ctx.service.snapshot())

    def toggle_pause(self) -> None:
        snap = self.ctx.service.snapshot()
        if snap.lifecycle is Lifecycle.RUNNING:
            self.ctx.service.pause()
        elif snap.lifecycle is Lifecycle.PAUSED:
            self.ctx.service.resume()
        self.poll()

    def toggle_break(self) -> None:
        snap = self.ctx.service.snapshot()
        if snap.lifecycle is Lifecycle.RUNNING:
            self.ctx.service.set_break(not snap.on_break)
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
        self.overlay.refresh(snap)
        self._refresh_session_return(snap)
        health = self.ctx.recording_health()
        self.tray.update_state(snap, self.ctx.recording_state, health, self.ctx.timer_countdown)
        if self.stack.currentIndex() == ACTIVITY:
            self.activity.set_recording_health(health)
        elif self.stack.currentIndex() == HOME:
            self.home.set_recording_health(health)
        if self._last_lifecycle in ACTIVE and snap.lifecycle is Lifecycle.FINISHED:
            self._last_lifecycle = snap.lifecycle
            self._on_finished(snap)
        self._last_lifecycle = snap.lifecycle

    def _refresh_session_return(self, snap: LiveSnapshot) -> None:
        "The sidebar card back to the live session: shown only while one is in progress."
        active = snap.lifecycle in ACTIVE
        if active:
            planned = snap.config.planned_minutes * 60 if snap.config else 0
            state = (
                tr("Paused")
                if snap.lifecycle is Lifecycle.PAUSED
                else timer_text(snap.active_s, planned, self.ctx.timer_countdown)
            )
            self.session_return.setText(tr("Session in progress\n{p0} · Return", p0=state))
        self.session_return.setVisible(active)

    def _mark_session_return(self) -> None:
        "Styled as the current place while the session page is shown (no menu row is)."
        current = self.stack.currentIndex() == SESSION
        if self.session_return.property("current") != current:
            self.session_return.setProperty("current", current)
            self.session_return.style().unpolish(self.session_return)
            self.session_return.style().polish(self.session_return)

    def _on_finished(self, snap: LiveSnapshot) -> None:
        self.home.set_running(False)
        self.settings.set_session_active(False)
        if snap.planned_reached:
            self.show_normal()
            self.tray.showMessage(
                "FocusLab", tr("The target time was reached and the session has ended.")
            )
        if snap.config is not None and snap.config.challenge:
            if snap.challenge_over:
                self.show_normal()
            self._show_challenge_result(snap)
        else:
            self._ask_self_report(snap.session_id)
        self.home.refresh()
        self.open_report(snap.session_id)

    def _show_challenge_result(self, snap: LiveSnapshot) -> None:
        "The challenge's record: how long it lasted, against the best earlier one."
        lasted = format_duration(snap.active_s)
        if snap.challenge_over:
            text = tr("You were away for 5 minutes in total, so the challenge has ended.")
        else:
            text = tr("You ended the challenge.")
        if snap.active_s > snap.challenge_best_s:
            text += "\n" + tr("New record: {p0}", p0=lasted)
        else:
            best = format_duration(snap.challenge_best_s)
            text += "\n" + tr("Lasted {p0} · Best {p1}", p0=lasted, p1=best)
        QMessageBox.information(self, tr("Focus challenge"), text)

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

    def _confirm_quit(self) -> bool:
        if self.ctx.service.snapshot().lifecycle not in ACTIVE:
            return True
        self.show_normal()
        answer = QMessageBox.question(
            self, tr("Quit FocusLab"), tr("End the current session and quit FocusLab?")
        )
        return answer == QMessageBox.StandardButton.Yes

    def quit_app(self) -> None:
        if not self._confirm_quit():
            return
        self.close_down()
        QApplication.quit()

    # updates ------------------------------------------------------------------------
    def _show_update(self, version: str) -> None:
        self.update_button.setText(tr("Update to v{p0}", p0=version))
        self.update_button.setVisible(True)

    def _update_now(self) -> None:
        "Sidebar 'Update to vX': open Settings > Updates and start right away."
        self.go(SETTINGS)
        self.settings.start_update()

    def _restart_for_update(self, staged: Path) -> None:
        """Quit, then let the helper swap the unpacked folder in and start the new exe."""
        if not self._confirm_quit():
            return
        self.close_down()
        updater.launch_swap(staged, updater.install_dir(), os.getpid())
        QApplication.quit()

    def close_down(self) -> None:
        """Stop the UI timers first so no late tick touches the closed database, then the
        report worker, the recorder and the session service."""
        self._timer.stop()
        self._activity_timer.stop()
        self.overlay.close()
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


def run_app(demo: bool = False, background: bool = False) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FocusLab")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)

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
    apply_theme(app, ctx.theme)
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
    if ctx.needs_guide and window.isVisible():
        window.show_guide()
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


def _global_rect(*widgets: QWidget) -> QRect | None:
    "The rectangle around the visible ones of `widgets`, in global coordinates."
    rect = QRect()
    for widget in widgets:
        if widget.isVisible():
            rect = rect.united(QRect(widget.mapToGlobal(widget.rect().topLeft()), widget.size()))
    return rect if not rect.isEmpty() else None

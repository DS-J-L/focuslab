"""Main window: navigation, session start/finish flow, tray and application bootstrap."""

import sys
from dataclasses import replace

from PySide6.QtCore import QLockFile, QTimer
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
from focuslab.config import data_dir, face_model_path
from focuslab.domain.models import SessionConfig
from focuslab.services.session_service import Lifecycle, LiveSnapshot
from focuslab.ui.consent import ask_activity_consent, ask_camera_consent
from focuslab.ui.context import AppContext
from focuslab.ui.home_page import HomePage
from focuslab.ui.report_page import ReportPage
from focuslab.ui.session_page import SessionPage
from focuslab.ui.settings_page import SettingsPage
from focuslab.ui.theme import ACCENT, SELF_REPORT_LABELS, STYLESHEET
from focuslab.ui.tray import Tray, make_icon

HOME, SESSION, REPORT, SETTINGS = range(4)
ACTIVE = (Lifecycle.RUNNING, Lifecycle.PAUSED)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("FocusLab" + (" (데모 센서)" if ctx.demo else ""))
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
        self.nav.addItems(["홈", "세션", "리포트", "설정"])
        side.addWidget(self.nav, 1)
        footer = QLabel(f"v{__version__} · 로컬 전용" + ("\n데모 센서 모드" if ctx.demo else ""),
                        objectName="BrandSub")
        side.addWidget(footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.home = HomePage(ctx)
        self.session = SessionPage(ctx)
        self.report = ReportPage(ctx)
        self.settings = SettingsPage(ctx)
        for page in (self.home, self.session, self.report, self.settings):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._navigate)
        self.home.startRequested.connect(self.start_session)
        self.home.openReport.connect(self.open_report)
        self.session.finishRequested.connect(self.finish_session)
        self.report.dataChanged.connect(self.home.refresh)
        self.settings.dataChanged.connect(self._data_changed)

        self.tray = Tray(self)
        if Tray.isSystemTrayAvailable():
            self.tray.show()
        self._tray_hint_shown = False
        self._last_lifecycle = Lifecycle.IDLE

        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.poll)
        self._timer.start()
        self.nav.setCurrentRow(HOME)
        self.home.refresh()

    # navigation ---------------------------------------------------------------------
    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == HOME:
            self.home.refresh()
        elif index == REPORT:
            self.report.refresh()
        elif index == SETTINGS:
            self.settings.refresh()
            self.settings.set_session_active(self._last_lifecycle in ACTIVE)

    def go(self, index: int) -> None:
        self.nav.setCurrentRow(index)

    def open_report(self, session_id: int) -> None:
        self.go(REPORT)
        self.report.show_session(session_id)

    def _data_changed(self) -> None:
        self.home.refresh()
        self.report.refresh()

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
                    self, "얼굴 모델 없음",
                    "얼굴 모델이 없어 이번 세션은 PC 활동만 사용합니다.\n"
                    "설정 > 카메라에서 모델을 받을 수 있습니다.",
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
        answer = QMessageBox.question(self, "세션 종료", "세션을 종료하고 리포트를 볼까요?")
        if answer == QMessageBox.StandardButton.Yes:
            self.ctx.service.finish()
            self.poll()

    def poll(self) -> None:
        snap = self.ctx.service.snapshot()
        self.session.refresh(snap)
        self.tray.update_state(snap)
        if self._last_lifecycle in ACTIVE and snap.lifecycle is Lifecycle.FINISHED:
            self._last_lifecycle = snap.lifecycle
            self._on_finished(snap)
        self._last_lifecycle = snap.lifecycle

    def _on_finished(self, snap: LiveSnapshot) -> None:
        self.home.set_running(False)
        self.settings.set_session_active(False)
        if snap.planned_reached:
            self.show_normal()
            self.tray.showMessage("FocusLab", "목표 시간에 도달해 세션을 종료했습니다.")
        self._ask_self_report(snap.session_id)
        self.home.refresh()
        self.open_report(snap.session_id)

    def _ask_self_report(self, session_id: int) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("세션 완료")
        box.setText("목표를 달성했나요? (자기보고, 리포트에서 바꿀 수 있습니다)")
        buttons = {
            box.addButton(text, QMessageBox.ButtonRole.AcceptRole): key
            for key, text in SELF_REPORT_LABELS.items()
        }
        box.addButton("건너뛰기", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        value = buttons.get(box.clickedButton())
        if value:
            self.ctx.service.set_self_report(session_id, value)

    # closing ------------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.ctx.service.snapshot().lifecycle in ACTIVE and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage(
                    "FocusLab",
                    "트레이에서 세션 기록을 계속합니다. 아이콘을 눌러 다시 열 수 있습니다.",
                )
                self._tray_hint_shown = True
            return
        event.ignore()
        self.quit_app()

    def quit_app(self) -> None:
        if self.ctx.service.snapshot().lifecycle in ACTIVE:
            self.show_normal()
            answer = QMessageBox.question(
                self, "FocusLab 종료", "진행 중인 세션을 종료하고 FocusLab을 끝낼까요?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._timer.stop()
        self.ctx.service.shutdown()
        self.tray.hide()
        QApplication.quit()


def _set_windows_app_id() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FocusLab.App")


def run_app(demo: bool = False) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("FocusLab")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)
    if sys.platform == "win32":
        app.setFont(QFont("Malgun Gothic", 10))

    # One instance per data folder: a second one would mark the live session as interrupted.
    lock_path = data_dir() / "focuslab.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "FocusLab", "FocusLab이 이미 실행 중입니다. 트레이 아이콘을 확인하세요."
        )
        return 1

    ctx = AppContext(demo)
    recovered = ctx.service.recover_interrupted()
    with ctx.service.lock:
        ctx.service.repository.purge_older_than(ctx.retention_days)
    window = MainWindow(ctx)
    window.show()
    if recovered:
        QMessageBox.information(
            window, "이전 세션 복구",
            f"정상 종료되지 않은 세션 {len(recovered)}개를 '중단됨'으로 저장했습니다.\n"
            "기록은 리포트에서 확인할 수 있습니다.",
        )
    code = app.exec()
    lock.unlock()
    return code


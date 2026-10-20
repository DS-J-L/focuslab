"""GUI flow with scripted sensors: start, pause/resume, break, correction, finish, close."""

import os
import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import REPORT, SESSION, SETTINGS, MainWindow


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def config(minutes=0):
    return SessionConfig("GUI 테스트", SessionMode.CODING, minutes, ("code.exe",), True)


def snapshot(win):
    return win.ctx.service.snapshot()


def test_full_session_flow(window, qtbot):
    window.start_session(config())
    assert window.stack.currentIndex() == SESSION
    assert window.home.fab.text() == "진행 중인 세션으로 돌아가기"
    assert window.session_return.isVisibleTo(window)
    qtbot.waitUntil(lambda: snapshot(window).active_s >= 2, timeout=6000)
    window.poll()
    assert window.session.badge.text() != "대기 중"
    assert "데모 카메라" in window.session.camera_flag.text()  # demo never opens a camera

    window.session.pause_button.click()
    assert snapshot(window).lifecycle is Lifecycle.PAUSED
    assert window.ctx.service.face_source.status.value == "OFF"
    window.toggle_pause()
    assert snapshot(window).lifecycle is Lifecycle.RUNNING

    window.session._correct(FocusState.BREAK)
    assert "정정" in window.session.feedback.text()

    window.finish_session()
    assert snapshot(window).lifecycle is Lifecycle.FINISHED
    assert window.stack.currentIndex() == REPORT
    assert window.home.fab.text() == "+"
    assert not window.session_return.isVisibleTo(window)
    report = window.report._report
    assert report is not None and report.record.goal == "GUI 테스트"
    assert report.metrics.corrected_segments == 1
    assert window.report.segments.rowCount() >= 1


def test_report_correction_and_delete(window, qtbot):
    window.start_session(config())
    qtbot.waitUntil(lambda: snapshot(window).active_s >= 1, timeout=6000)
    window.finish_session()
    page = window.report
    page.show_all.setChecked(True)
    page.segments.selectRow(0)
    page.correct_label.setCurrentIndex(page.correct_label.findData(FocusState.AWAY))
    page._apply_correction()
    assert page._report.segments[0].corrected_label is FocusState.AWAY
    page.show_all.setChecked(True)
    page.segments.selectRow(0)
    page._clear_correction()
    assert page._report.segments[0].corrected_label is None
    page._delete()
    with window.ctx.service.lock:
        assert window.ctx.service.repository.list_sessions() == []


def test_settings_page_renders(window):
    window.go(SETTINGS)
    assert window.settings.activity_state.text()
    window.settings.refresh()


def test_update_check_offers_a_newer_release(window, qtbot, monkeypatch):
    from focuslab import updater

    release = updater.Release("99.0.0", "https://example.invalid/releases/v99.0.0", None, None)
    monkeypatch.setattr(updater, "latest_release", lambda: release)
    opened = []
    monkeypatch.setattr("focuslab.ui.settings_page.QDesktopServices.openUrl", opened.append)
    assert not window.update_button.isVisible()
    window.settings.check_updates()
    qtbot.waitUntil(window.update_button.isVisible, timeout=5000)
    assert "99.0.0" in window.update_button.text()
    window.update_button.click()
    assert window.stack.currentIndex() == SETTINGS
    window.settings.update_button.click()  # a source checkout opens the release page instead
    assert opened[0].toString() == release.page_url


def test_update_check_without_any_release(window, qtbot, monkeypatch):
    import urllib.error

    from focuslab import updater

    def missing():
        raise urllib.error.HTTPError(updater.LATEST_URL, 404, "Not Found", {}, None)

    monkeypatch.setattr(updater, "latest_release", missing)
    window.settings.check_updates()
    qtbot.waitUntil(window.settings.update_check.isEnabled, timeout=5000)
    assert window.settings.update_state.text() == "아직 공개된 릴리스가 없습니다."
    assert not window.update_button.isVisible()


def test_restart_for_update_swaps_only_after_shutting_down(qtbot, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "focuslab.ui.main_window.updater.launch_swap", lambda *args: calls.append(args)
    )
    monkeypatch.setattr("focuslab.ui.main_window.QApplication.quit", lambda: calls.append("quit"))
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.settings.restartForUpdate.emit(tmp_path / ".FocusLab-update")
    staged, _target, pid = calls[0]
    assert staged == tmp_path / ".FocusLab-update" and pid == os.getpid()
    assert calls[1] == "quit"
    assert not win._timer.isActive()  # close_down ran before the helper started


def test_quit_releases_all_workers(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("focuslab.ui.main_window.QApplication.quit", lambda: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.start_session(config())
    qtbot.waitUntil(lambda: snapshot(win).active_s >= 1, timeout=6000)
    win.quit_app()
    assert snapshot(win).lifecycle is Lifecycle.FINISHED
    assert not [t for t in threading.enumerate() if t.name.startswith("focuslab-")]


def test_no_timer_tick_reaches_the_database_after_close_down(qtbot, monkeypatch):
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.start_session(config())
    qtbot.waitUntil(lambda: snapshot(win).active_s >= 1, timeout=6000)
    win.close_down()
    qtbot.wait(1200)  # longer than the 500 ms poll interval
    assert not win._timer.isActive() and not win._activity_timer.isActive()


def test_popups_stay_readable_on_a_dark_system_palette(qapp, qtbot):
    from PySide6.QtGui import QColor, QPalette

    from focuslab.ui.theme import apply_theme

    previous_palette, previous_sheet = qapp.palette(), qapp.styleSheet()
    previous_font, previous_style = qapp.font(), qapp.style().name()
    dark = QPalette(QColor("#1e1e1e"))  # what Windows dark mode hands Qt
    qapp.setPalette(dark)
    try:
        apply_theme(qapp)
        box = QMessageBox(QMessageBox.Icon.Information, "t", "popup text")
        qtbot.addWidget(box)
        box.ensurePolished()
        # The stylesheet's dark text (#1F2430) must sit on a light popup background.
        assert box.palette().window().color().lightness() > 200
        assert box.palette().windowText().color().lightness() < 100
    finally:
        qapp.setStyle(previous_style)
        qapp.setFont(previous_font)
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_sheet)

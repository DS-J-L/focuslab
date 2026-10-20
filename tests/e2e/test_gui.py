"""GUI flow with scripted sensors: start, pause/resume, break, correction, finish, close."""

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
    window.home.startRequested.emit(config())
    assert window.stack.currentIndex() == SESSION
    assert not window.home.start_button.isEnabled()
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
    assert window.home.start_button.isEnabled()
    report = window.report._report
    assert report is not None and report.record.goal == "GUI 테스트"
    assert report.metrics.corrected_segments == 1
    assert window.report.segments.rowCount() >= 1


def test_report_correction_and_delete(window, qtbot):
    window.home.startRequested.emit(config())
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


def test_quit_releases_all_workers(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("focuslab.ui.main_window.QApplication.quit", lambda: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.home.startRequested.emit(config())
    qtbot.waitUntil(lambda: snapshot(win).active_s >= 1, timeout=6000)
    win.quit_app()
    assert snapshot(win).lifecycle is Lifecycle.FINISHED
    assert not [t for t in threading.enumerate() if t.name.startswith("focuslab-")]


def test_no_timer_tick_reaches_the_database_after_close_down(qtbot, monkeypatch):
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.home.startRequested.emit(config())
    qtbot.waitUntil(lambda: snapshot(win).active_s >= 1, timeout=6000)
    win.close_down()
    qtbot.wait(1200)  # longer than the 500 ms poll interval
    assert not win._timer.isActive() and not win._activity_timer.isActive()


def test_popups_stay_readable_on_a_dark_system_palette(qapp, qtbot):
    from PySide6.QtGui import QColor, QPalette

    from focuslab.ui.main_window import apply_theme

    previous_palette, previous_sheet = qapp.palette(), qapp.styleSheet()
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
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_sheet)

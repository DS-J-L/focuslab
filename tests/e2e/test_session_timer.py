"""Session clocks count up from 0 or, with a target time, show the time left; chosen in
Settings or by clicking the clock, and the same everywhere a session time is shown."""

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.activity.recorder import RecorderState
from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import SESSION, SETTINGS, MainWindow
from focuslab.ui.widgets import timer_text


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def start(window, minutes):
    window.start_session(SessionConfig("타이머", SessionMode.CODING, minutes, ("code.exe",), False))
    window.poll()


def test_timer_text_counts_up_down_and_into_overtime():
    assert timer_text(60, 25 * 60, countdown=False) == "01:00"
    assert timer_text(60, 25 * 60, countdown=True) == "24:00"
    assert timer_text(25 * 60, 25 * 60, countdown=True) == "00:00"
    assert timer_text(26 * 60 + 5, 25 * 60, countdown=True) == "+01:05"
    assert timer_text(60, 0, countdown=True) == "01:00"  # no target: nothing to count down
    assert timer_text(2 * 3600, 3 * 3600, countdown=True) == "1:00:00"


def test_counting_up_is_the_default(window):
    start(window, 25)
    assert not window.ctx.timer_countdown
    assert window.session.clock.text().startswith("00:0")
    assert "남은 시간" in window.session.remaining.text()
    assert window.session.clock.toolTip() == "눌러서 남은 시간 보기"


def test_clicking_the_clock_switches_every_session_clock(window):
    start(window, 25)
    page, overlay = window.session, window.overlay
    page.clock.click()
    assert window.ctx.timer_countdown
    assert page.clock.text().startswith(("24:", "25:00"))
    assert "경과 00:0" in page.remaining.text()
    assert page.clock.toolTip() == "눌러서 0부터 세기"
    assert "24:" in window.session_return.text() or "25:00" in window.session_return.text()
    assert overlay.time.text().endswith("남음") and overlay.mini_time.text().startswith("2")
    window.tray.update_state(window.ctx.service.snapshot(), RecorderState.STOPPED, countdown=True)
    assert "세션 24:" in window.tray.toolTip() or "세션 25:00" in window.tray.toolTip()

    page.clock.click()  # and back
    assert not window.ctx.timer_countdown
    assert page.clock.text().startswith("00:0")
    assert not overlay.time.text().endswith("남음")


def test_overtime_shows_how_far_past_the_target(window):
    start(window, 1)
    window.ctx.set_flag("ui.timer_countdown", True)
    snap = replace(window.ctx.service.snapshot(), active_s=75)  # 15 s past a 1-minute target
    window.session.refresh(snap)
    window.overlay.refresh(snap)
    assert window.session.clock.text() == "+00:15"
    assert window.overlay.time.text() == "0분 15초 초과"


def test_without_a_target_time_the_clock_always_counts_up(window):
    window.ctx.set_flag("ui.timer_countdown", True)
    start(window, 0)
    page = window.session
    assert page.clock.text().startswith("00:0") and page.clock.toolTip() == ""
    page.clock.click()  # nothing to switch to
    assert window.ctx.timer_countdown
    assert window.stack.currentIndex() == SESSION


def test_settings_choose_the_timer_mode(window):
    window.go(SETTINGS)
    combo = window.settings.timer_mode
    assert [combo.itemText(i) for i in range(combo.count())] == ["0부터 세기", "남은 시간 표시"]
    assert combo.currentIndex() == 0
    combo.setCurrentIndex(1)
    assert window.ctx.timer_countdown
    start(window, 25)
    window.session.clock.click()  # switched back from the session page
    window.go(SETTINGS)
    assert combo.currentIndex() == 0

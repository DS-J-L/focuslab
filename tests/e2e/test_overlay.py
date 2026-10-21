"""Floating session overlay: parrot controls, hover, animation, collapse, hide, position."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from focuslab.domain.models import Decision, FocusState, SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle, LiveSnapshot
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.mascot.behavior_policy import Mood
from focuslab.ui.mascot.director import BREAK, MOTION, PAUSE
from focuslab.ui.overlay import MARGIN, POS_KEY, long_text, session_seconds


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def start(win):
    win.start_session(
        SessionConfig("오버레이", SessionMode.CODING, 0, ("code.exe",), False)
    )


def snapshot(win):
    return win.ctx.service.snapshot()


def mouse(overlay, kind, global_pos, buttons=Qt.MouseButton.LeftButton):
    local = QPointF(global_pos - overlay.pos())
    event = QMouseEvent(
        kind, local, QPointF(global_pos), Qt.MouseButton.LeftButton, buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    {
        QEvent.Type.MouseButtonPress: overlay.mousePressEvent,
        QEvent.Type.MouseMove: overlay.mouseMoveEvent,
        QEvent.Type.MouseButtonRelease: overlay.mouseReleaseEvent,
    }[kind](event)


def test_session_time_excludes_breaks_and_is_written_out():
    snap = LiveSnapshot(active_s=1400, seconds={FocusState.ON_TASK: 1000, FocusState.BREAK: 6})
    assert session_seconds(snap) == 1394
    assert long_text(1394) == "23분 14초"
    assert long_text(3725) == "1시간 2분 5초"


def test_overlay_follows_the_session(window, qtbot):
    overlay = window.overlay
    assert not overlay.isVisible()
    start(window)
    assert overlay.isVisible()
    assert overlay.status.text() == "집중 중"
    # Top-right of the screen by default.
    geo = QGuiApplication.primaryScreen().availableGeometry()
    assert overlay.x() + overlay.width() == geo.x() + geo.width() - MARGIN
    assert overlay.y() == geo.y() + MARGIN

    qtbot.waitUntil(lambda: snapshot(window).active_s >= 1, timeout=6000)
    overlay.pause_button.click()
    assert snapshot(window).lifecycle is Lifecycle.PAUSED
    window.poll()
    assert overlay.status.text() == "일시정지 중"
    assert overlay.pause_button.text() == "재개"
    stopped = overlay.time.text()
    window.poll()
    assert overlay.time.text() == stopped
    overlay.pause_button.click()
    assert snapshot(window).lifecycle is Lifecycle.RUNNING

    window.ctx.service.set_break(True)
    window.poll()
    assert overlay.status.text() == "휴식 중"
    window.ctx.service.set_break(False)

    overlay.finish_button.click()  # confirmed by the patched question box
    assert snapshot(window).lifecycle is Lifecycle.FINISHED
    assert not overlay.isVisible()


def test_collapse_expand_and_hide(window, qtbot):
    overlay = window.overlay
    start(window)
    right = overlay.x() + overlay.width()
    overlay.collapse_button.click()
    assert overlay.collapsed and not overlay.full.isVisible()
    assert overlay.x() + overlay.width() == right  # resizes toward the left
    window.poll()
    assert ":" in overlay.mini_time.text()

    centre = overlay.pos() + QPoint(5, 5)
    mouse(overlay, QEvent.Type.MouseButtonPress, centre)
    mouse(overlay, QEvent.Type.MouseButtonRelease, centre, Qt.MouseButton.NoButton)
    assert not overlay.collapsed and overlay.full.isVisible()

    overlay.close_button.click()
    assert not overlay.isVisible()
    assert snapshot(window).lifecycle is Lifecycle.RUNNING  # only the overlay is hidden
    window.poll()
    assert not overlay.isVisible()
    window.session.overlay_button.click()
    assert overlay.isVisible()


def test_dragged_position_is_remembered(window):
    overlay = window.overlay
    start(window)
    grab = overlay.pos() + QPoint(5, 5)
    mouse(overlay, QEvent.Type.MouseButtonPress, grab)
    mouse(overlay, QEvent.Type.MouseMove, grab - QPoint(120, -60))
    mouse(overlay, QEvent.Type.MouseButtonRelease, grab - QPoint(120, -60), Qt.MouseButton.NoButton)
    moved = overlay.pos()
    assert window.ctx.setting(POS_KEY) == f"{moved.x() + overlay.width()},{moved.y()}"
    overlay.hide()
    window.show_overlay()
    assert overlay.pos() == moved

    window.ctx.set_setting(POS_KEY, "-90000,-90000")  # a monitor that is gone
    window.show_overlay()
    geo = QGuiApplication.primaryScreen().availableGeometry()
    assert overlay.x() + overlay.width() == geo.x() + geo.width() - MARGIN


def test_setting_turns_the_overlay_off(window):
    window.settings.overlay_on_start.setChecked(False)
    assert not window.ctx.overlay_on_start
    start(window)
    assert snapshot(window).lifecycle is Lifecycle.RUNNING
    assert not window.overlay.isVisible()
    window.session.overlay_button.click()  # still available on demand
    assert window.overlay.isVisible()


def test_yellow_parrot_takes_a_break_and_is_unavailable_while_paused(window, qtbot):
    overlay = window.overlay
    start(window)
    assert overlay.break_button.text() == "휴식 시작"
    overlay.break_button.click()
    assert snapshot(window).on_break
    assert overlay.status.text() == "휴식 중"
    assert overlay.break_button.text() == "휴식 종료"
    assert overlay.break_button.icon_name == "back"
    overlay.break_button.click()
    assert not snapshot(window).on_break

    overlay.pause_button.click()
    assert not overlay.break_button.isEnabled()
    assert overlay.pause_button.emblem == "play"
    overlay.break_button.click()  # disabled: nothing happens
    assert not snapshot(window).on_break


def test_hovering_a_parrot_shows_its_action_in_a_bubble(window):
    overlay = window.overlay
    start(window)
    perch = overlay.perch
    QApplication.sendEvent(overlay.finish_button, QEvent(QEvent.Type.Enter))
    assert perch.director.hover == 1
    assert overlay.finish_button.icon_name == "stop"
    QApplication.sendEvent(overlay.finish_button, QEvent(QEvent.Type.Leave))
    assert perch.director.hover is None
    QApplication.sendEvent(overlay.close_button, QEvent(QEvent.Type.Enter))
    assert perch.director.hover == "window"


def test_parrots_animate_only_while_expanded_and_shown(window):
    overlay = window.overlay
    start(window)
    assert overlay.perch.animating
    overlay.collapse_button.click()
    assert not overlay.perch.animating  # the mini overlay has no parrots to move
    overlay.set_collapsed(False)
    assert overlay.perch.animating
    overlay.close_button.click()
    assert not overlay.perch.animating


def test_the_three_parrots_are_drawn_in_their_colours(window):
    overlay = window.overlay
    start(window)
    image = overlay.perch.grab().toImage()

    ratio = image.devicePixelRatio()

    def count(colour, x_range):
        target = QColor(colour)
        hits = 0
        for x in range(*x_range, 2):
            for y in range(70, 170, 2):
                c = image.pixelColor(int(x * ratio), int(y * ratio))
                diff = (c.red() - target.red(), c.green() - target.green())
                hits += max(map(abs, (*diff, c.blue() - target.blue()))) < 12
        return hits

    seats = (("#E8483F", (45, 112)), ("#3E72E6", (117, 184)), ("#F8C935", (189, 256)))
    for colour, x_range in seats:
        assert count(colour, x_range) > 100, colour


def test_parrot_movement_setting_reaches_the_overlay(window):
    combo = window.settings.mascot_motion
    assert combo.currentData() == "normal"
    assert window.overlay.perch.director.motion == MOTION["normal"]
    combo.setCurrentIndex(combo.findData("minimal"))
    assert window.ctx.mascot_motion == "minimal"
    assert window.overlay.perch.director.motion == MOTION["minimal"]
    combo.setCurrentIndex(combo.findData("lively"))
    assert window.overlay.perch.director.motion == MOTION["lively"]


def test_overlay_parrots_react_to_estimated_off_task_time(window):
    overlay = window.overlay
    start(window)
    t = [1000.0]
    overlay.perch.clock = lambda: t[0]
    running = snapshot(window)

    def at(seconds, state):
        t[0] = 1000.0 + seconds
        overlay.refresh(replace(running, decision=Decision(state, 0.7)))
        return overlay.perch.director.mood

    assert at(0, FocusState.POSSIBLY_OFF_TASK) is Mood.WATCH
    assert at(31, FocusState.POSSIBLY_OFF_TASK) is Mood.WARN
    assert at(32, FocusState.ON_TASK) is Mood.CHEER

    window.settings.mascot_reactions.setChecked(False)
    assert not window.ctx.mascot_reactions
    assert at(40, FocusState.POSSIBLY_OFF_TASK) is Mood.CALM
    assert at(100, FocusState.POSSIBLY_OFF_TASK) is Mood.CALM


def test_frames_slow_down_while_the_parrots_only_breathe(window):
    from focuslab.ui.overlay import FRAME_MS, RESTING_FRAME_MS

    window.settings.mascot_motion.setCurrentIndex(window.settings.mascot_motion.findData("minimal"))
    overlay = window.overlay
    start(window)
    perch = overlay.perch
    t = [100.0]
    perch.clock = lambda: t[0]
    image = perch.grab()  # paints a frame
    assert perch.director.resting and perch._timer.interval() == RESTING_FRAME_MS
    QApplication.sendEvent(overlay.pause_button, QEvent(QEvent.Type.Enter))
    t[0] += 0.05
    perch.grab()
    assert not perch.director.resting and perch._timer.interval() == FRAME_MS
    QApplication.sendEvent(overlay.pause_button, QEvent(QEvent.Type.Leave))
    for _ in range(40):  # settles back within a second or so
        t[0] += 0.05
        perch.grab()
    assert perch._timer.interval() == RESTING_FRAME_MS
    assert not image.isNull()


def test_studio_overlay_shows_action_captions_and_target_progress(window):
    window.start_session(
        SessionConfig("Illustration test", SessionMode.CODING, 25, ("code.exe",), False)
    )
    overlay = window.overlay
    perch = overlay.perch
    assert tuple(label.text() for label in perch.action_labels) == (
        overlay.pause_button.text(),
        overlay.finish_button.text(),
        overlay.break_button.text(),
    )
    assert perch.progress_fraction == 0
    assert perch.visual_state == "focusing"

    # The progress indicator is visual only; the elapsed-time calculation is unchanged.
    fake_snapshot = replace(snapshot(window), active_s=750)
    overlay.refresh(fake_snapshot)
    assert perch.progress_fraction == pytest.approx(0.5)

    image = perch.grab().toImage()
    assert not image.isNull()
    assert image.pixelColor(150, 43).alpha() > 0  # panel is actually painted

    overlay.pause_button.click()
    assert perch.visual_state == "paused"
    assert perch.action_labels[PAUSE].text() == overlay.pause_button.text()
    assert not perch.action_labels[BREAK].isEnabled()
    overlay.pause_button.click()

    overlay.break_button.click()
    assert perch.visual_state == "break"
    assert perch.action_labels[BREAK].text() == overlay.break_button.text()

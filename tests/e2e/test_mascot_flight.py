"""The opt-in flying parrot: when it flies, that it always comes home, and its safety rules."""

import random
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QMessageBox

from focuslab.domain.models import Decision, FocusState, SessionConfig, SessionMode
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.mascot.flight_overlay import FlightController, plan_sortie
from focuslab.ui.mascot.renderer import BLUE, RED, YELLOW

AREA = QRectF(0, 0, 1920, 1040)
HOME = QPointF(1700, 150)


class Flight:
    def __init__(self, fullscreen=False):
        self.t = 0.0
        self.landed = []
        self.full = fullscreen
        self.c = FlightController(
            clock=lambda: self.t,
            home=lambda i: HOME,
            area=lambda: AREA,
            plumage=lambda i: (RED, BLUE, YELLOW)[i],
            rng=random.Random(1),
            fullscreen=lambda: self.full,
        )
        self.c.enabled = True
        self.c.landed.connect(self.landed.append)

    def run(self, seconds):
        end = self.t + seconds
        while self.t < end and self.c.flying:
            self.t += 0.05
            self.c._frame()


@pytest.fixture
def flight(qtbot):
    f = Flight()
    yield f
    f.c.abort()
    f.c.window.close()


def test_a_sortie_swoops_to_three_spots_inside_the_screen_and_hovers_at_each():
    legs = plan_sortie(HOME, AREA, random.Random(2))
    assert [leg.hover for leg in legs] == [False, True] * 3
    assert legs[0].p0 == HOME
    for prev, nxt in zip(legs, legs[1:], strict=False):
        assert prev.point(1.0) == nxt.point(0.0)  # one continuous path
    for leg in legs[1::2]:
        assert AREA.contains(leg.p0) and leg.duration >= 2


def test_it_flies_only_when_enabled_and_alarmed_then_always_comes_home(flight):
    c = flight.c
    c.enabled = False
    c.consider(True, True)
    assert not c.flying
    c.enabled = True
    c.consider(False, True)
    assert not c.flying
    c.consider(True, True)
    assert c.flying and c.flier == 0 and c.window.isVisible()

    flight.run(2.5)  # out over the screen, hovering with the bubble
    assert c.window.bubble
    assert c.window.pose.scale > 1.3

    c.consider(False, True)  # back on task: home at once
    assert c.returning and not c.window.bubble
    flight.run(5)
    assert not c.flying and not c.window.isVisible() and flight.landed == [0]


def test_an_outing_ends_by_itself_and_does_not_repeat_within_the_interval(flight):
    c = flight.c
    c.interval_s = 300
    c.consider(True, True)
    flight.run(60)
    assert not c.flying and flight.landed == [0]
    c.consider(True, True)  # still off task, but it flew a moment ago
    assert not c.flying
    flight.t += 300
    c.consider(True, True)
    assert c.flying and c.flier == 1  # the next parrot takes a turn


def test_clicking_the_parrot_shoos_it_home(flight):
    c = flight.c
    c.consider(True, True)
    flight.run(1)
    c.window.shooed.emit()
    assert c.returning and c.window.pose.eyes == "wide"
    c.consider(True, True)  # still alarmed: it keeps going home
    flight.run(5)
    assert not c.flying


def test_never_over_full_screen_programs_and_gone_at_once_when_not_allowed(qtbot):
    f = Flight(fullscreen=True)
    f.c.consider(True, True)
    assert not f.c.flying
    f.full = False
    f.c.consider(True, True)
    assert f.c.flying
    f.c.consider(True, False)  # overlay hidden or session over: vanish
    assert not f.c.flying and not f.c.window.isVisible() and f.landed == [0]
    f.c.window.close()


# With the real overlay ---------------------------------------------------------------
@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    monkeypatch.setattr(
        "focuslab.ui.mascot.flight_overlay.foreground_is_fullscreen", lambda: False
    )
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def off_task_for(win, seconds, state=FocusState.POSSIBLY_OFF_TASK):
    overlay = win.overlay
    t = [5000.0]
    overlay.perch.clock = lambda: t[0]
    win.start_session(SessionConfig("비행", SessionMode.CODING, 0, ("code.exe",), False))
    running = win.ctx.service.snapshot()
    for s in range(0, int(seconds) + 1):
        t[0] = 5000.0 + s
        overlay.refresh(replace(running, decision=Decision(state, 0.7)))
    return t, running


def test_flying_is_off_by_default(window):
    assert not window.settings.mascot_flight.isChecked()
    assert not window.settings.flight_after.isEnabled()
    off_task_for(window, 120)
    assert not window.overlay.flight.flying


def test_a_parrot_leaves_the_branch_after_a_minute_and_lands_back(window):
    window.settings.mascot_flight.setChecked(True)
    assert window.ctx.flight_enabled and window.settings.flight_after.isEnabled()
    overlay = window.overlay
    t, running = off_task_for(window, 59)
    assert not overlay.flight.flying
    t[0] += 2
    overlay.refresh(replace(running, decision=Decision(FocusState.POSSIBLY_OFF_TASK, 0.7)))
    assert overlay.flight.flying
    i = overlay.flight.flier
    assert i in overlay.perch.director.away
    assert not overlay.perch.parrots[i].isVisibleTo(overlay)  # no button on the empty seat
    assert overlay.perch.director.poses(t[0])[i].alpha == 0

    overlay.refresh(replace(running, decision=Decision(FocusState.ON_TASK, 0.9)))
    assert overlay.flight.returning
    while overlay.flight.flying:
        t[0] += 0.05
        overlay.flight._frame()
    assert i not in overlay.perch.director.away
    assert overlay.perch.parrots[i].isVisibleTo(overlay)
    assert overlay.perch.director.actors[i].behavior.name == "land"


def test_threshold_setting_and_hiding_the_overlay_stops_a_flight(window):
    window.settings.mascot_flight.setChecked(True)
    window.settings.flight_after.setValue(120)
    assert window.overlay.policy.alarm_after == 120
    overlay = window.overlay
    t, running = off_task_for(window, 100)
    assert not overlay.flight.flying
    off = replace(running, decision=Decision(FocusState.POSSIBLY_OFF_TASK, 0.7))
    t[0] += 30
    overlay.refresh(off)
    assert overlay.flight.flying
    overlay.close_button.click()  # the user hid the overlay
    assert not overlay.flight.flying and not overlay.flight.window.isVisible()

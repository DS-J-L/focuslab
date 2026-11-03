import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.overlay import SEATS


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    win.start_session(SessionConfig("Petting test", SessionMode.CODING, 0, ("code.exe",), False))
    win.now = 100.0
    win.overlay.perch.clock = lambda: win.now
    yield win
    win.close_down()


def move(win, index, ys, buttons=Qt.MouseButton.NoButton):
    perch = win.overlay.perch
    button = perch.parrots[index]
    for y in ys:
        win.now += .12
        pos = QPointF(SEATS[index], y) - QPointF(button.pos())
        global_pos = QPointF(button.mapToGlobal(pos.toPoint()))
        event = QMouseEvent(QEvent.Type.MouseMove, pos, global_pos, Qt.MouseButton.NoButton,
                            buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(button, event)


@pytest.mark.parametrize("index", range(3))
def test_hover_pets_each_parrot_without_clicking_or_changing_the_session(window, index):
    perch = window.overlay.perch
    before = window.ctx.service.snapshot()
    position = window.overlay.pos()
    move(window, index, [100, 120, 140, 120, 100, 120, 140])
    assert perch.director.actors[index].content(window.now)
    assert sum(actor.content(window.now) for actor in perch.director.actors) == 1
    after = window.ctx.service.snapshot()
    assert after.lifecycle is Lifecycle.RUNNING and not after.on_break
    assert after.session_id == before.session_id
    assert window.overlay.pos() == position
    window.now += .5
    perch.grab()  # actual image rig and heart rendering
    window.now += .3
    assert perch.director.poses(window.now)[index].emote == "pet-heart"


def test_held_button_and_necklace_hover_do_not_count_as_petting(window):
    move(window, 0, [100, 120, 140, 120, 100, 120, 140], Qt.MouseButton.LeftButton)
    move(window, 1, [164, 174, 184, 174, 164, 174, 184])
    assert not any(actor.content(window.now) for actor in window.overlay.perch.director.actors)


def test_disabled_yellow_necklace_during_pause_still_allows_petting(window):
    window.overlay.pause_button.click()
    assert not window.overlay.break_button.isEnabled()
    move(window, 2, [100, 120, 140, 120, 100, 120, 140])
    assert window.overlay.perch.director.actors[2].content(window.now)
    snap = window.ctx.service.snapshot()
    assert snap.lifecycle is Lifecycle.PAUSED and not snap.on_break


def test_leave_and_collapse_clear_unfinished_gestures(window):
    perch = window.overlay.perch
    move(window, 0, [100, 120, 140, 120])
    QApplication.sendEvent(perch.parrots[0], QEvent(QEvent.Type.Leave))
    move(window, 0, [120, 100, 120])
    assert not perch.director.actors[0].content(window.now)
    window.overlay.set_collapsed(True)
    window.overlay.set_collapsed(False)
    move(window, 0, [120, 140, 120])
    assert not perch.director.actors[0].content(window.now)

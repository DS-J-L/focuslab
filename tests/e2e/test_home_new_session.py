"""Home's (+) opens the new session popup; the live session is reached from the sidebar."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.home_page import FAB_MARGIN
from focuslab.ui.main_window import HOME, REPORT, SESSION, MainWindow
from focuslab.ui.new_session_dialog import NewSessionDialog


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def fill_and(action):
    "Replace the modal exec(): fill in the popup, then press Start or Cancel."

    def run(dialog):
        dialog.goal.setText("새 구조 테스트")
        dialog.mode.setCurrentIndex(dialog.mode.findData(SessionMode.LECTURE))
        dialog.minutes.setValue(0)
        dialog.camera.setChecked(False)
        (dialog.start_button if action == "start" else dialog.cancel_button).click()
        return dialog.result()

    return run


def snapshot(win):
    return win.ctx.service.snapshot()


def test_sidebar_has_no_session_row(window):
    assert [window.nav.item(i).text() for i in range(window.nav.count())] == [
        "홈",
        "활동",
        "리포트",
        "설정",
    ]
    window.go(REPORT)
    assert window.stack.currentIndex() == REPORT and window.nav.currentRow() == 2
    assert not window.session_return.isVisibleTo(window)


def test_fab_floats_bottom_right_and_says_new_session(window, qtbot):
    home = window.home
    fab = home.fab
    assert fab.text() == "+" and fab.toolTip() == "새 세션"
    assert fab.width() == fab.height()
    assert fab.geometry().right() == home.width() - FAB_MARGIN - 1
    assert fab.geometry().bottom() == home.height() - FAB_MARGIN - 1
    window.resize(1000, 690)  # small enough to scroll
    qtbot.waitUntil(lambda: home.findChild(QScrollArea).verticalScrollBar().maximum() > 0)
    before = fab.pos()
    home.findChild(QScrollArea).verticalScrollBar().setValue(10_000)
    assert fab.pos() == before
    assert fab.geometry().bottom() == home.height() - FAB_MARGIN - 1


def test_cancel_starts_nothing(window, monkeypatch):
    monkeypatch.setattr(NewSessionDialog, "exec", fill_and("cancel"))
    window.home.fab.click()
    assert snapshot(window).lifecycle is Lifecycle.IDLE
    assert window.stack.currentIndex() == HOME
    assert window.ctx.setting("last.goal", "") != "새 구조 테스트"


def test_start_opens_the_live_session_with_the_popup_settings(window, monkeypatch):
    monkeypatch.setattr(NewSessionDialog, "exec", fill_and("start"))
    window.home.fab.click()
    snap = snapshot(window)
    assert snap.lifecycle is Lifecycle.RUNNING
    assert snap.config.goal == "새 구조 테스트" and snap.config.mode is SessionMode.LECTURE
    assert window.stack.currentIndex() == SESSION and window.nav.currentRow() == -1
    assert window.ctx.setting("last.goal", "") == "새 구조 테스트"
    assert window.ctx.setting("last.mode", "") == SessionMode.LECTURE.value


def test_in_progress_session_is_reachable_and_not_duplicated(window, monkeypatch):
    def no_popup(dialog):
        raise AssertionError("the popup must not open while a session is running")

    window.start_session(SessionConfig("진행 중", SessionMode.CODING, 0, ("code.exe",), False))
    sid = snapshot(window).session_id
    monkeypatch.setattr(NewSessionDialog, "exec", no_popup)

    window.go(HOME)
    assert window.home.fab.text() == "진행 중인 세션으로 돌아가기"
    assert window.home.fab.width() > window.home.fab.height()
    assert window.session_return.isVisibleTo(window)
    assert "진행 중인 세션" in window.session_return.text()
    assert "돌아가기" in window.session_return.text()
    assert not window.session_return.property("current")

    window.home.fab.click()  # back to the session, no second one
    assert window.stack.currentIndex() == SESSION
    assert window.session_return.property("current")

    window.go(REPORT)
    window.session_return.click()
    assert window.stack.currentIndex() == SESSION and window.nav.currentRow() == -1
    # Tabbing into the menu must not pick its first row and leave the session.
    tab_in = QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason)
    QApplication.sendEvent(window.nav, tab_in)
    assert window.stack.currentIndex() == SESSION and window.nav.currentRow() == -1
    window.nav.setCurrentRow(0)  # any menu row navigates away again
    assert window.stack.currentIndex() == HOME

    window.start_session(SessionConfig("두 번째", SessionMode.CODING, 0, (), False))
    assert snapshot(window).session_id == sid and snapshot(window).config.goal == "진행 중"

    window.toggle_pause()
    assert "일시정지" in window.session_return.text()
    window.finish_session()
    assert snapshot(window).lifecycle is Lifecycle.FINISHED
    assert not window.session_return.isVisibleTo(window)
    assert window.home.fab.text() == "+"


def test_empty_allow_list_can_be_declined_in_the_popup(qtbot, monkeypatch):
    ctx = AppContext(demo=True)
    try:
        dialog = NewSessionDialog(ctx)
        qtbot.addWidget(dialog)
        dialog.apps.clear()
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )
        dialog.start_button.click()
        assert dialog.result() != NewSessionDialog.DialogCode.Accepted
        assert dialog.config().allowed_apps == ()
    finally:
        ctx.service.shutdown()

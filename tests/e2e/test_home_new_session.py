"""Home's (+) opens the new session bubble above it; the live session is reached from the
sidebar."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.i18n import set_language
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.home_page import FAB_MARGIN
from focuslab.ui.main_window import HOME, REPORT, SESSION, MainWindow
from focuslab.ui.new_session_popover import SHADOW


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def open_bubble(window, qtbot):
    "Press (+) and wait for the bubble's fade-in to finish."
    window.home.fab.click()
    bubble = window.home.popover
    assert bubble is not None and bubble.is_open()
    qtbot.waitUntil(lambda: bubble.graphicsEffect() is None)
    return bubble


def fill(bubble):
    bubble.form.goal.setText("새 구조 테스트")
    bubble.form.mode.setCurrentIndex(bubble.form.mode.findData(SessionMode.LECTURE))
    bubble.form.minutes.setValue(0)
    bubble.form.camera.setChecked(False)


def wait_closed(window, qtbot):
    qtbot.waitUntil(lambda: window.home.popover is None)
    assert window.home.fab.text() == "+"


def tail_tip(bubble):
    "The lowest painted pixel row; the widget's transparent shadow margin is below it."
    return bubble.geometry().bottom() - SHADOW


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


def test_bubble_opens_in_the_page_right_above_the_fab(window, qtbot):
    home, fab = window.home, window.home.fab
    bubble = open_bubble(window, qtbot)
    assert not bubble.isWindow() and bubble.parentWidget() is home  # no separate popup window
    assert home.rect().contains(bubble.geometry())
    assert tail_tip(bubble) < fab.geometry().top()
    assert fab.y() > bubble.y() and home.children().index(fab) > home.children().index(bubble)
    assert bubble.geometry().right() > fab.geometry().right()  # right-aligned, shadow beyond
    assert fab.text() == "×" and fab.toolTip() == "닫기"
    assert QApplication.focusWidget() is bubble.form.goal
    assert not bubble.form.apps_panel.isVisibleTo(bubble)  # allowed apps start folded
    count = bubble.form.apps.count()
    assert bubble.form.apps_toggle.text() == f"{count}개 허용 · 편집"
    bubble.form.apps_toggle.click()
    assert bubble.form.apps_panel.isVisibleTo(bubble)
    assert bubble.form.apps_toggle.text() == f"{count}개 허용 · 접기"


def test_cancel_starts_nothing(window, qtbot):
    bubble = open_bubble(window, qtbot)
    fill(bubble)
    bubble.cancel_button.click()
    wait_closed(window, qtbot)
    assert snapshot(window).lifecycle is Lifecycle.IDLE
    assert window.stack.currentIndex() == HOME
    assert window.ctx.setting("last.goal", "") != "새 구조 테스트"


def test_start_opens_the_live_session_with_the_bubble_settings(window, qtbot):
    bubble = open_bubble(window, qtbot)
    fill(bubble)
    bubble.start_button.click()
    assert window.home.popover is None
    snap = snapshot(window)
    assert snap.lifecycle is Lifecycle.RUNNING
    assert snap.config.goal == "새 구조 테스트" and snap.config.mode is SessionMode.LECTURE
    assert window.stack.currentIndex() == SESSION and window.nav.currentRow() == -1
    assert window.ctx.setting("last.goal", "") == "새 구조 테스트"
    assert window.ctx.setting("last.mode", "") == SessionMode.LECTURE.value


def test_enter_in_the_goal_starts_but_enter_in_the_app_field_only_adds(window, qtbot):
    bubble = open_bubble(window, qtbot)
    bubble.form.show_apps(True)
    bubble.form.manual_app.setText("Notion.exe")
    qtbot.keyClick(bubble.form.manual_app, Qt.Key.Key_Return)
    assert "notion.exe" in bubble.form._current_apps()
    assert "notion.exe" in window.ctx.allowed_apps(bubble.form.current_mode())
    assert bubble.form.manual_app.text() == "" and window.home.popover is bubble
    assert snapshot(window).lifecycle is Lifecycle.IDLE
    qtbot.keyClick(bubble.form.goal, Qt.Key.Key_Return)
    assert snapshot(window).lifecycle is Lifecycle.RUNNING


def test_escape_the_fab_a_click_elsewhere_or_leaving_home_closes_the_bubble(window, qtbot):
    bubble = open_bubble(window, qtbot)
    qtbot.keyClick(bubble.form.goal, Qt.Key.Key_Escape)
    wait_closed(window, qtbot)

    open_bubble(window, qtbot)
    window.home.fab.click()  # (×)
    wait_closed(window, qtbot)

    bubble = open_bubble(window, qtbot)
    qtbot.mouseClick(bubble.form.goal, Qt.MouseButton.LeftButton)  # inside: stays open
    assert window.home.popover is bubble
    qtbot.mouseClick(window.home.recent.viewport(), Qt.MouseButton.LeftButton)
    wait_closed(window, qtbot)

    open_bubble(window, qtbot)
    window.go(REPORT)
    assert window.home.popover is None
    window.go(HOME)
    assert window.home.fab.text() == "+"
    assert snapshot(window).lifecycle is Lifecycle.IDLE


def test_bubble_stays_inside_a_small_window_and_scrolls(window, qtbot):
    window.resize(980, 680)  # the minimum window size
    bubble = open_bubble(window, qtbot)
    bubble.form.show_apps(True)
    home = window.home
    assert home.rect().contains(bubble.geometry())
    assert tail_tip(bubble) < home.fab.geometry().top()
    qtbot.waitUntil(lambda: bubble.scroll.verticalScrollBar().maximum() > 0)
    window.resize(1180, 820)
    qtbot.waitUntil(lambda: tail_tip(bubble) < home.fab.geometry().top())
    assert home.rect().contains(bubble.geometry())


@pytest.mark.parametrize("language", ["ko", "en"])
def test_the_form_never_scrolls_sideways(qtbot, language):
    set_language(language)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.resize(980, 680)
    win.show()
    try:
        bubble = open_bubble(win, qtbot)
        for shown in (False, True):
            bubble.form.show_apps(shown)
            qtbot.wait(20)
            assert bubble.scroll.horizontalScrollBar().maximum() == 0, shown
    finally:
        win.close_down()


def test_in_progress_session_is_reachable_and_not_duplicated(window, qtbot):
    bubble = open_bubble(window, qtbot)
    window.start_session(SessionConfig("진행 중", SessionMode.CODING, 0, ("code.exe",), False))
    assert window.home.popover is None and not bubble.is_open()  # a running session closes it
    sid = snapshot(window).session_id

    window.go(HOME)
    assert window.home.fab.text() == "진행 중인 세션으로 돌아가기"
    assert window.home.fab.width() > window.home.fab.height()
    assert window.session_return.isVisibleTo(window)
    assert "진행 중인 세션" in window.session_return.text()
    assert "돌아가기" in window.session_return.text()
    assert not window.session_return.property("current")

    window.home.fab.click()  # back to the session, no second one and no bubble
    assert window.home.popover is None
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


def test_empty_allow_list_can_be_declined_in_the_bubble(window, qtbot, monkeypatch):
    bubble = open_bubble(window, qtbot)
    bubble.form.apps.clear()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    bubble.start_button.click()
    assert window.home.popover is bubble and bubble.is_open()
    assert snapshot(window).lifecycle is Lifecycle.IDLE
    assert bubble.form.config().allowed_apps == ()

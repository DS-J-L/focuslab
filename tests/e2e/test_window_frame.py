"""The window draws its own title bar: the sidebar and page reach the top edge, the caption
buttons work, and Windows is told which parts drag, resize, or open snap layouts."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.window_frame import (
    HTBOTTOM,
    HTBOTTOMRIGHT,
    HTCAPTION,
    HTCLIENT,
    HTLEFT,
    HTMAXBUTTON,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    RESIZE_BORDER,
    TITLE_HEIGHT,
    hit_test,
    native_frame_available,
)


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.resize(1180, 820)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win.close_down()


def center(widget, window):
    return widget.mapTo(window, widget.rect().center())


def test_sidebar_and_page_reach_the_top_with_the_caption_buttons_on_the_page(window):
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    bar = window.title_bar
    sidebar = window.findChild(QWidget, "Sidebar")
    assert sidebar.mapTo(window, QPoint(0, 0)) == QPoint(0, 0)
    assert bar.mapTo(window, QPoint(0, 0)) == QPoint(sidebar.width(), 0)
    assert bar.height() == TITLE_HEIGHT and bar.width() == window.width() - sidebar.width()
    assert window.stack.mapTo(window, QPoint(0, 0)).y() == TITLE_HEIGHT
    close = bar.close_button.mapTo(window, bar.close_button.rect().topRight())
    assert close == QPoint(window.width() - 1, 0)
    assert [b.toolTip() for b in (bar.min_button, bar.max_button, bar.close_button)] == [
        "최소화",
        "최대화",
        "닫기",
    ]
    assert not native_frame_available() and window._frame is None  # off-screen: no Win32 hooks


def test_caption_buttons_maximize_restore_minimize_and_close(window, qtbot, monkeypatch):
    bar = window.title_bar
    bar.max_button.click()
    qtbot.waitUntil(window.isMaximized)
    assert bar.max_button.maximized and bar.max_button.toolTip() == "이전 크기로 복원"
    bar.max_button.click()
    qtbot.waitUntil(lambda: not window.isMaximized())
    assert not bar.max_button.maximized and bar.max_button.toolTip() == "최대화"
    bar.min_button.click()
    qtbot.waitUntil(window.isMinimized)
    window.showNormal()
    closed = []
    monkeypatch.setattr(window, "close", lambda: closed.append(True))
    bar.close_button.click()
    assert closed == [True]


def test_double_clicking_the_title_bar_toggles_maximize(window, qtbot):
    qtbot.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))
    qtbot.waitUntil(window.isMaximized)
    qtbot.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))
    qtbot.waitUntil(lambda: not window.isMaximized())


def test_hit_test_tells_windows_where_to_drag_resize_and_snap(window, qtbot):
    bar, w, h = window.title_bar, window.width(), window.height()
    edge = RESIZE_BORDER - 1
    expected = {
        QPoint(0, 0): HTTOPLEFT,
        QPoint(w - 1, 0): HTTOPRIGHT,
        QPoint(400, edge): HTTOP,
        QPoint(edge, 400): HTLEFT,
        QPoint(w - 1, 400): HTRIGHT,
        QPoint(400, h - 1): HTBOTTOM,
        QPoint(w - 1, h - 1): HTBOTTOMRIGHT,
        QPoint(100, 15): HTCAPTION,  # the top of the sidebar drags too
        QPoint(500, 15): HTCAPTION,
        center(bar.max_button, window): HTMAXBUTTON,  # snap layouts flyout
        center(bar.min_button, window): HTCLIENT,
        center(bar.close_button, window): HTCLIENT,
        QPoint(500, TITLE_HEIGHT + 200): HTCLIENT,
        center(window.nav, window): HTCLIENT,
    }
    assert {p: hit_test(window, bar, p) for p in expected} == expected

    window.showMaximized()
    qtbot.waitUntil(window.isMaximized)
    # A maximized window has no resize edges: the very top still drags.
    assert hit_test(window, bar, QPoint(0, 0)) == HTCAPTION
    assert hit_test(window, bar, QPoint(window.width() - 1, 400)) == HTCLIENT
    assert hit_test(window, bar, center(bar.max_button, window)) == HTMAXBUTTON

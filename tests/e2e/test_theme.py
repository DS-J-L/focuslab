"""Switching between the light and dark themes in Settings, live and persisted."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QStyleHints
from PySide6.QtWidgets import QMessageBox

from focuslab.domain.models import FocusState
from focuslab.ui import theme
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import SETTINGS, MainWindow
from focuslab.ui.theme import DARK, LIGHT, apply_theme


@pytest.fixture
def themed_app(qapp):
    "Leave the shared QApplication as other tests expect it: no stylesheet, light colors."
    previous_palette, previous_sheet = qapp.palette(), qapp.styleSheet()
    previous_font, previous_style = qapp.font(), qapp.style().name()
    yield qapp
    theme._active, theme._choice = LIGHT, "light"
    qapp.styleHints().unsetColorScheme()
    qapp.setStyle(previous_style)
    qapp.setFont(previous_font)
    qapp.setPalette(previous_palette)
    qapp.setStyleSheet(previous_sheet)


@pytest.fixture
def window(qtbot, themed_app):
    ctx = AppContext(demo=True)
    apply_theme(themed_app, ctx.theme)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def choose(win, value: str) -> None:
    combo = win.settings.theme_combo
    combo.setCurrentIndex(combo.findData(value))


def test_settings_switch_the_theme_live_and_remember_it(window, themed_app, qtbot):
    win = window
    assert win.ctx.theme == "light" and theme.colors() is LIGHT
    combo = win.settings.theme_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["light", "dark", "system"]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "라이트",
        "다크",
        "Windows 설정 따르기",
    ]
    light_sheet = themed_app.styleSheet()

    win.go(SETTINGS)
    choose(win, "dark")
    assert theme.colors() is DARK
    assert themed_app.styleSheet() != light_sheet and DARK.window in themed_app.styleSheet()
    assert themed_app.palette().window().color().name().upper() == DARK.window
    assert themed_app.palette().text().color().name().upper() == DARK.text
    # Persisted: a new context (the next launch) reads the same choice.
    assert win.ctx.setting("ui.theme") == "dark"
    assert AppContext(demo=True).theme == "dark"

    # Native popups follow Qt's palette, so they turn dark as well.
    box = QMessageBox(QMessageBox.Icon.Information, "t", "popup text")
    qtbot.addWidget(box)
    box.ensurePolished()
    assert box.palette().window().color().lightness() < 60
    assert box.palette().windowText().color().lightness() > 200

    # Widgets that draw their own colors pick up the palette without a restart.
    badge = win.session.badge
    badge.set_state(FocusState.ON_TASK)
    badge.ensurePolished()
    assert badge.palette().window().color().name().upper() == DARK.states[FocusState.ON_TASK]
    assert badge.palette().windowText().color().name().upper() == DARK.on_state
    assert DARK.states[FocusState.ON_TASK] in _legend_html(win.session)

    choose(win, "light")
    assert theme.colors() is LIGHT and LIGHT.window in themed_app.styleSheet()
    assert themed_app.palette().window().color().name().upper() == LIGHT.window
    assert LIGHT.states[FocusState.ON_TASK] in _legend_html(win.session)
    assert win.ctx.setting("ui.theme") == "light"


def _legend_html(page) -> str:
    from focuslab.ui.widgets import Legend

    return page.findChild(Legend).label.text()


def test_follow_windows_uses_the_windows_app_mode(window, themed_app, monkeypatch):
    windows_mode = [Qt.ColorScheme.Dark]
    monkeypatch.setattr(QStyleHints, "colorScheme", lambda self: windows_mode[0])
    choose(window, "system")
    assert window.ctx.theme == "system" and theme.colors() is DARK
    # Windows switches to light apps while FocusLab runs.
    windows_mode[0] = Qt.ColorScheme.Light
    theme._follow_windows(themed_app)
    assert theme.colors() is LIGHT
    assert themed_app.palette().window().color().name().upper() == LIGHT.window


def test_unknown_saved_theme_falls_back_to_light(themed_app):
    ctx = AppContext(demo=True)
    ctx.set_setting("ui.theme", "sepia")
    assert ctx.theme == "light"
    with pytest.raises(ValueError):
        ctx.set_theme("sepia")

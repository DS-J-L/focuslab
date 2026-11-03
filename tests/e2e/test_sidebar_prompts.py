"""The rotating sidebar stays readable and never moves navigation or a live session."""

import pytest
from PySide6.QtCore import QRect, Qt

from focuslab.i18n import korean_catalog, tr
from focuslab.ui import theme
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.sidebar_prompts import PROMPTS, ROTATE_MS


@pytest.fixture
def window(qtbot, qapp):
    previous = (qapp.palette(), qapp.styleSheet(), qapp.font(), qapp.style().name(),
                theme._active, theme._choice)
    theme.apply_theme(qapp, "light")
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.resize(980, 680)
    win.show()
    yield win
    win.close_down()
    palette, sheet, font, style, theme._active, theme._choice = previous
    qapp.styleHints().unsetColorScheme()
    qapp.setStyle(style)
    qapp.setFont(font)
    qapp.setPalette(palette)
    qapp.setStyleSheet(sheet)


def test_fifty_translated_prompts_are_shuffled_without_repeats(window):
    assert len(PROMPTS) == len(set(PROMPTS)) == 50
    assert len({korean_catalog()[message] for message in PROMPTS}) == 50
    prompt = window.tagline
    previous = None
    for _ in range(2):
        seen = set()
        for _ in range(50):
            assert prompt.message != previous
            assert prompt.text() == tr(prompt.message)
            seen.add(prompt.message)
            previous = prompt.message
            prompt.advance()
        assert seen == set(PROMPTS)


@pytest.mark.parametrize("language", ["en", "ko"])
def test_all_prompts_fit_both_themes_without_moving_navigation(window, qapp, language):
    from focuslab.i18n import set_language

    set_language(language)
    prompt = window.tagline
    for choice in ("light", "dark"):
        theme.apply_theme(qapp, choice)
        qapp.processEvents()
        top, height = window.nav.y(), prompt.height()
        for _ in range(50):
            prompt.advance()
            margins = prompt.contentsMargins()
            width = prompt.width() - margins.left() - margins.right()
            available = prompt.height() - margins.top() - margins.bottom()
            required = prompt.fontMetrics().boundingRect(
                QRect(0, 0, width, 1000), Qt.TextFlag.TextWordWrap, prompt.text()
            ).height()
            assert required <= available, (language, choice, prompt.text(), required, available)
            assert (window.nav.y(), prompt.height()) == (top, height)
        qapp.processEvents()
        assert window.nav.y() == top


def test_timer_rotates_only_while_visible_and_stops_at_shutdown(window, qtbot):
    prompt = window.tagline
    assert prompt._timer.interval() == ROTATE_MS == 600_000
    before = prompt.text()
    prompt._timer.start(20)  # exercise the actual Qt timeout connection without a 10-minute wait
    qtbot.waitUntil(lambda: prompt.text() != before)
    prompt._timer.setInterval(600_000)
    window.hide()
    before = prompt.text()
    assert not prompt._timer.isActive()
    prompt._timer.timeout.emit()
    assert prompt.text() == before
    window.showNormal()
    assert prompt._timer.isActive()
    window.showMinimized()
    prompt._timer.timeout.emit()
    assert prompt.text() == before
    window.showNormal()
    window.close_down()
    assert not prompt._timer.isActive()

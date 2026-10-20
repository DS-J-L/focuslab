"""Language precedence, lazy labels, safe interpolation, and catalog completeness."""

import ast
from pathlib import Path
from string import Formatter

import pytest

from focuslab import __main__
from focuslab.config import MODE_LABELS
from focuslab.domain.models import FocusState, SessionMode
from focuslab.focus.metrics import format_duration
from focuslab.i18n import (
    get_language,
    initialize_language,
    korean_catalog,
    set_language,
    tr,
    weekday_name,
)
from focuslab.ui.theme import STATE_LABELS


@pytest.mark.parametrize(
    "saved,override,expected",
    [
        (None, None, "en"),
        ("en", None, "en"),
        ("ko", None, "ko"),
        ("ko", "en", "en"),
        ("bad-value", None, "en"),
    ],
)
def test_language_precedence(monkeypatch, saved, override, expected):
    monkeypatch.delenv("FOCUSLAB_LANGUAGE", raising=False)
    if override:
        monkeypatch.setenv("FOCUSLAB_LANGUAGE", override)
    assert initialize_language(saved) == expected
    assert get_language() == expected


def test_labels_imported_before_language_selection_follow_the_selected_language():
    set_language("en")
    assert MODE_LABELS[SessionMode.CODING] == "Coding"
    assert STATE_LABELS[FocusState.BREAK] == "Break"
    assert format_duration(3660) == "1h 1m"
    assert weekday_name(0) == "Mon"
    set_language("ko")
    assert MODE_LABELS[SessionMode.CODING] == "코딩"
    assert STATE_LABELS[FocusState.BREAK] == "휴식"
    assert format_duration(3660) == "1시간 1분"
    assert weekday_name(0) == "월"


def test_user_content_is_neither_translated_nor_reinterpreted_as_a_template():
    path = r"C:\개인 자료\{p0}\Saved.txt"
    set_language("ko")
    assert tr("Saved:\n{p0}", p0=path) == "저장했습니다:\n" + path
    assert tr("unknown-message") == "unknown-message"
    with pytest.raises(ValueError, match="Unsupported language"):
        set_language("fr")


def test_every_catalog_entry_preserves_placeholder_names_conversions_and_specs():
    formatter = Formatter()

    def placeholders(message):
        return sorted(
            (name, spec, conversion)
            for _, name, spec, conversion in formatter.parse(message)
            if name is not None
        )

    for english, korean in korean_catalog().items():
        assert korean.strip(), english
        assert placeholders(english) == placeholders(korean), english


def test_all_literal_messages_and_label_dictionaries_have_korean_translations():
    """Catch untranslated new labels without matching runtime implementation branches."""
    root = Path(__file__).resolve().parents[2] / "src" / "focuslab"
    catalog = korean_catalog()
    missing = []
    for path in root.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "tr" and node.args:
                argument = node.args[0]
                message = (
                    argument.value
                    if isinstance(argument, ast.Constant)
                    else constants.get(argument.id)
                    if isinstance(argument, ast.Name)
                    else None
                )
                if isinstance(message, str) and message not in catalog:
                    missing.append((path.name, node.lineno, message))
            if node.func.id == "LocalizedMapping":
                for value in node.args[0].values:
                    if isinstance(value, ast.Constant) and value.value not in catalog:
                        missing.append((path.name, node.lineno, value.value))
    assert not missing, missing


def test_cli_language_override_reaches_application_startup(monkeypatch):
    selected = []
    monkeypatch.setattr(
        "focuslab.ui.main_window.run_app",
        lambda **kwargs: selected.append(initialize_language("ko")) or 0,
    )
    assert __main__.main(["--demo", "--language", "en"]) == 0
    assert selected == ["en"]

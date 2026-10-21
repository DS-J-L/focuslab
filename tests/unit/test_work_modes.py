"""The user's own work modes: saved form, tolerant loading, labels and hints."""

from focuslab.config import DEFAULT_ALLOWED_APPS, mode_label
from focuslab.domain.models import SessionMode
from focuslab.i18n import korean_catalog, set_language
from focuslab.work_modes import (
    BUILT_IN,
    CUSTOM_PREFIX,
    MAX_NAME,
    PRESET_PREFIX,
    PRESETS,
    WorkMode,
    dump_custom,
    load_custom,
    new_mode,
)


def test_built_in_keys_are_the_session_mode_values():
    "Allowed apps saved before custom modes existed stay under the same setting keys."
    assert [m.key for m in BUILT_IN] == [m.value for m in SessionMode]
    assert all(m.name is None for m in BUILT_IN)


def test_new_mode_is_named_keyed_and_round_trips():
    mode = new_mode("  디자인   작업 ", SessionMode.LECTURE)
    assert mode.key.startswith(CUSTOM_PREFIX) and mode.name == "디자인 작업"
    assert new_mode("디자인", SessionMode.LECTURE).key != mode.key
    assert load_custom(dump_custom([mode])) == [mode]
    assert mode.default_apps == DEFAULT_ALLOWED_APPS[SessionMode.LECTURE]
    assert len(new_mode("가" * 100, SessionMode.CODING).name) == MAX_NAME


def test_damaged_settings_never_break_the_mode_list():
    good = {"key": "custom:a1", "base": "READING_WRITING", "name": "시험 준비"}
    raw = (
        '[{"key": "custom:a1", "base": "READING_WRITING", "name": "시험 준비"},'
        ' {"key": "custom:b", "base": "DANCING", "name": "x"},'
        ' {"key": "CODING", "base": "CODING", "name": "fake built-in"},'
        ' {"key": "custom:c", "base": "CODING", "name": "   "},'
        ' {"key": "custom:d", "base": "CODING"}, 3, null]'
    )
    assert load_custom(raw) == [WorkMode(good["key"], SessionMode.READING_WRITING, "시험 준비")]
    assert load_custom("not json") == load_custom('{"a": 1}') == load_custom(None) == []


def test_labels_and_hints_follow_the_language():
    mode = WorkMode("custom:x", SessionMode.READING_WRITING, "Exam prep")
    set_language("en")
    assert mode.label == mode_label(SessionMode.READING_WRITING, "Exam prep") == "Exam prep"
    assert mode.hint.startswith("Estimated like Reading / writing.")
    assert BUILT_IN[0].label == mode_label(SessionMode.CODING) == "Coding"
    set_language("ko")
    assert mode.hint.startswith("독서·필기처럼 판정합니다.")
    assert BUILT_IN[0].label == "코딩"


def test_presets_have_their_own_apps_names_and_translations():
    keys = [m.key for m in PRESETS]
    assert len(set(keys)) == len(keys) and all(k.startswith(PRESET_PREFIX) for k in keys)
    catalog = korean_catalog()
    for mode in PRESETS:
        assert mode.preset and mode.base != SessionMode.CUSTOM
        assert mode.name in catalog and mode.about in catalog
        assert mode.default_apps == mode.apps and mode.apps == tuple(map(str.lower, mode.apps))
    design = next(m for m in PRESETS if m.key == "preset:design")
    assert "figma.exe" in design.default_apps
    assert "figma.exe" not in DEFAULT_ALLOWED_APPS[design.base]
    set_language("ko")
    assert design.label == design.session_name == "디자인"
    assert design.hint.endswith("코딩처럼 판정합니다.")
    set_language("en")
    assert design.label == "Design" and design.hint.endswith("Estimated like Coding.")
    assert BUILT_IN[0].session_name is None

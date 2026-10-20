from focuslab.activity.auto_sessions import (
    AutoSessionConfig,
    detect_sessions,
    link_manual_sessions,
)
from focuslab.activity.classifier import UserRules
from focuslab.domain.activity import ActivitySpan, Category, SpanKind

MIN = 60_000


def timeline(*parts):
    """``(minutes, exe, domain)``, ``(minutes, "IDLE")`` or ``(minutes, None)`` for a gap."""
    spans, t = [], 0
    for minutes, *what in parts:
        length = round(minutes * MIN)
        if what == [None]:
            t += length
            continue
        if what == ["IDLE"]:
            spans.append(ActivitySpan(t, t + length, SpanKind.IDLE, span_id=len(spans) + 1))
        else:
            exe, domain = (what + [None])[:2]
            spans.append(ActivitySpan(t, t + length, SpanKind.ACTIVE, exe, domain=domain,
                                      span_id=len(spans) + 1))
        t += length
    return spans


def summary(sessions):
    return [(s.start_ms // MIN, s.end_ms // MIN, s.category) for s in sessions]


def test_related_switches_stay_in_one_session():
    spans = timeline((10, "code.exe"), (0.1, "explorer.exe"), (3, "chrome.exe", "github.com"),
                     (12, "windowsterminal.exe"), (1, "code.exe"))
    [session] = detect_sessions(spans)
    assert summary([session]) == [(0, 26, Category.DEVELOPMENT)]
    assert session.switches == 3  # explorer is neutral and not a switch
    assert session.detours == 0 and session.interrupted_ms == 0


def test_long_idle_or_unobserved_time_splits_sessions():
    spans = timeline((20, "code.exe"), (10, "IDLE"), (15, "code.exe"), (8, None), (5, "code.exe"))
    assert summary(detect_sessions(spans)) == [
        (0, 20, Category.DEVELOPMENT), (30, 45, Category.DEVELOPMENT),
        (53, 58, Category.DEVELOPMENT),
    ]


def test_short_idle_is_an_interruption_and_never_trails_a_session():
    spans = timeline((10, "code.exe"), (2, "IDLE"), (10, "code.exe"), (3, "IDLE"))
    [session] = detect_sessions(spans)
    assert (session.start_ms, session.end_ms) == (0, 22 * MIN)
    assert session.interrupted_ms == 2 * MIN and session.active_ms == 20 * MIN


def test_a_sustained_new_kind_of_work_starts_a_new_session_at_the_switch():
    spans = timeline((20, "code.exe"), (20, "chrome.exe", "netflix.com"))
    assert summary(detect_sessions(spans)) == [
        (0, 20, Category.DEVELOPMENT), (20, 40, Category.ENTERTAINMENT),
    ]


def test_a_short_excursion_is_a_detour_with_its_return_time():
    spans = timeline((10, "code.exe"), (2, "chrome.exe", "netflix.com"), (1, "kakaotalk.exe"),
                     (10, "code.exe"))
    [session] = detect_sessions(spans)
    assert session.category is Category.DEVELOPMENT
    assert session.detours == 1 and session.return_ms == [3 * MIN]


def test_ambiguous_sites_are_observed_switches_not_off_task():
    spans = timeline((15, "code.exe"), (10, "chrome.exe", "youtube.com"))
    sessions = detect_sessions(spans)
    assert summary(sessions) == [(0, 15, Category.DEVELOPMENT), (15, 25, Category.UNKNOWN)]


def test_user_rules_change_the_grouping():
    spans = timeline((15, "code.exe"), (10, "chrome.exe", "youtube.com"))
    rules = UserRules({}, {"youtube.com": Category.DEVELOPMENT})  # coding tutorials
    assert summary(detect_sessions(spans, rules)) == [(0, 25, Category.DEVELOPMENT)]


def test_tiny_sessions_are_dropped_and_thresholds_are_configurable():
    spans = timeline((1, "code.exe"), (10, None), (3, "winword.exe"))
    assert summary(detect_sessions(spans)) == [(11, 14, Category.DOCUMENTATION)]
    cfg = AutoSessionConfig(break_split_s=60, switch_sustain_s=60, min_active_s=30)
    spans = timeline((3, "code.exe"), (2, "IDLE"), (3, "code.exe"))
    assert len(detect_sessions(spans, cfg=cfg)) == 2


def test_window_clips_spans_at_day_boundaries():
    spans = timeline((30, "code.exe"))
    [session] = detect_sessions(spans, window=(10 * MIN, 20 * MIN))
    assert (session.start_ms, session.end_ms) == (10 * MIN, 20 * MIN)


def test_manual_sessions_are_linked_by_largest_overlap():
    sessions = detect_sessions(timeline((30, "code.exe"), (10, None), (30, "code.exe")))
    link_manual_sessions(sessions, [(7, 25 * MIN, 45 * MIN), (8, 50 * MIN, 52 * MIN),
                                    (9, 55 * MIN, 69 * MIN)])
    assert [s.manual_session_id for s in sessions] == [7, 9]

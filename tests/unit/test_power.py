"""PC power-on time from power events, and the one-line sleep tip."""

import sys
import time

import pytest

from focuslab.activity.power import (
    EventLogPower,
    PowerEvent,
    PowerSettings,
    on_intervals,
    parse_event,
    power_report,
    sleep_tip,
)
from focuslab.domain.activity import ActivitySpan, SpanKind

M = 60_000
H = 60 * M


def on(t, boot=False):
    return PowerEvent(t, True, boot=boot)


def off(t):
    return PowerEvent(t, False)


def span(start, end, kind=SpanKind.ACTIVE):
    return ActivitySpan(start_ms=start, end_ms=end, kind=kind)


def test_boot_sleep_wake_shutdown_clipped_to_the_window():
    events = [on(1 * H, boot=True), off(3 * H), on(4 * H), off(6 * H)]
    assert on_intervals(events, 0, 24 * H) == [(1 * H, 3 * H), (4 * H, 6 * H)]
    assert on_intervals(events, 2 * H, 5 * H) == [(2 * H, 3 * H), (4 * H, 5 * H)]


def test_the_state_before_the_window_comes_from_the_last_earlier_event():
    assert on_intervals([on(-5 * H)], 0, 2 * H) == [(0, 2 * H)]  # still awake
    assert on_intervals([off(-5 * H)], 0, 2 * H) == []
    assert on_intervals([], 0, 2 * H) == []


def test_a_repeated_resume_is_ignored_and_a_boot_while_awake_closes_the_crashed_run():
    assert on_intervals([on(1 * H), on(2 * H), off(3 * H)], 0, 4 * H) == [(1 * H, 3 * H)]
    events = [on(1 * H, boot=True), on(2 * H), on(5 * H, boot=True), off(6 * H)]
    # No event says when the first run died: it ends at the last event seen in it.
    assert on_intervals(events, 0, 8 * H) == [(1 * H, 2 * H), (5 * H, 6 * H)]


def test_a_resume_report_wins_over_a_standby_exit_logged_during_hibernation():
    events = [
        on(0),
        off(1 * H),  # enters Modern Standby
        on(3 * H),  # "exits" standby to hibernate
        PowerEvent(1 * H, False, asleep_until_ms=8 * H),  # resume report: slept until 8 h
        on(8 * H),
    ]
    assert on_intervals(events, 0, 10 * H) == [(0, 1 * H), (8 * H, 10 * H)]


EVENT = (
    "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
    "<Provider Name='Microsoft-Windows-{provider}'/><EventID>{event_id}</EventID>"
    "<TimeCreated SystemTime='2026-10-21T08:14:08.9108251Z'/></System>"
    "<EventData>{data}</EventData></Event>"
)


def test_events_are_parsed_from_their_rendered_xml():
    sleep = parse_event(EVENT.format(provider="Kernel-Power", event_id=42, data=""))
    assert sleep == [PowerEvent(1792570448910, False)]
    boot = parse_event(EVENT.format(provider="Kernel-General", event_id=12, data=""))
    assert boot[0].on and boot[0].boot
    assert parse_event(EVENT.format(provider="Kernel-Power", event_id=41, data="")) == []
    resume = parse_event(
        EVENT.format(
            provider="Power-Troubleshooter",
            event_id=1,
            data="<Data Name='SleepTime'>2026-10-21T06:57:26.6335606Z</Data>"
            "<Data Name='WakeTime'>2026-10-21T08:14:07.9578504Z</Data>",
        )
    )
    assert resume == [
        PowerEvent(1792565846633, False, asleep_until_ms=1792570447957),
        PowerEvent(1792570447957, True),
    ]


def test_power_on_time_never_falls_below_what_was_recorded():
    spans = [
        span(1 * H, 2 * H),
        span(2 * H, 3 * H, SpanKind.IDLE),
        span(3 * H, 3 * H + 30 * M, SpanKind.LOCKED),
        span(9 * H, 10 * H),  # recorded although the log says asleep (missed event)
    ]
    report = power_report([(0, 4 * H)], spans, None)
    assert report.on_ms == 5 * H
    assert report.unrecorded_ms == 1 * H + 30 * M  # 0-1 h and 3:30-4 h
    assert report.unused_runs == [(2 * H, 3 * H + 30 * M)]  # idle then locked: one stretch
    assert report.tip is None  # no settings, no tip


def test_tip_when_sleep_is_off_counts_only_the_time_past_the_suggestion():
    never = PowerSettings(sleep_s=0, display_s=0)
    runs = [(0, 2 * H), (3 * H, 3 * H + 50 * M), (5 * H, 5 * H + 20 * M)]
    tip = sleep_tip(runs, never)
    assert (tip.blocked, tip.runs, tip.total_ms, tip.saved_ms) == (False, 2, 170 * M, 110 * M)
    assert sleep_tip([(0, 40 * M)], never) is None  # 10 minutes is not worth a line
    assert sleep_tip(runs, None) is None


def test_tip_when_sleep_is_set_but_something_kept_the_pc_awake():
    ten = PowerSettings(sleep_s=600, display_s=300)
    tip = sleep_tip([(0, 15 * M), (1 * H, 2 * H)], ten)
    assert (tip.blocked, tip.runs, tip.saved_ms, tip.sleep_s) == (True, 1, 50 * M, 600)
    assert sleep_tip([(0, 15 * M)], ten) is None  # within the margin: sleep worked


def test_event_log_reader_reads_nothing_without_consent():
    power = EventLogPower()
    power.enabled = False
    assert power.on_intervals(0, 1 * H) is None
    assert power.settings() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event log")
def test_event_log_reader_on_this_machine_returns_intervals_or_none():
    now = time.time_ns() // 1_000_000
    result = EventLogPower().on_intervals(now - 24 * H, now)
    assert result is None or all(now - 24 * H <= a < b <= now for a, b in result)

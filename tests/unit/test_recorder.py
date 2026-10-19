import sqlite3

import pytest

from focuslab.activity.recorder import ActivityRecorder, RecorderConfig, RecorderState
from focuslab.domain.activity import ForegroundApp, ProbeSample, SpanKind, SystemEvent
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.sqlite_db import connect

T0 = 1_760_000_000_000  # an arbitrary UTC epoch ms


class ScriptProbe:
    """Returns whatever ``current`` is set to; counts calls to prove pause reads nothing."""

    def __init__(self) -> None:
        self.current: ProbeSample | Exception = app("code.exe")
        self.calls = 0

    def sample(self) -> ProbeSample:
        self.calls += 1
        if isinstance(self.current, Exception):
            raise self.current
        return self.current


def app(exe: str | None, idle: float = 0.0) -> ProbeSample:
    return ProbeSample(ForegroundApp(exe, exe and exe.upper()), idle)


class Wall:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.offset = T0 - clock.ms

    def __call__(self) -> int:
        return self.clock.ms + self.offset


@pytest.fixture
def rig(tmp_path, clock):
    probe = ScriptProbe()
    wall = Wall(clock)
    recorders = []

    def make(**cfg):
        rec = ActivityRecorder(
            tmp_path / "a.db", probe, clock=clock, wall=wall, config=RecorderConfig(**cfg)
        )
        rec.start(run_thread=False)
        recorders.append(rec)
        return rec

    def stored():
        conn = connect(tmp_path / "a.db")
        repo = ActivityRepository(conn)
        spans = repo.spans_between(0, 2**62)
        events = [r["type"] for r in repo.events_between(0, 2**62)]
        conn.close()
        return spans, events

    def run(rec, seconds, step=1.0):
        for _ in range(int(seconds / step)):
            clock.advance(step)
            rec.tick()

    yield probe, wall, make, run, stored
    for rec in recorders:
        rec.stop()


def rel(spans):
    return [((s.start_ms - T0) // 1000, (s.end_ms - T0) // 1000, s.kind, s.exe_name) for s in spans]


def test_switches_create_contiguous_spans_and_same_app_extends(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()  # t=0
    run(rec, 3)
    probe.current = app("chrome.exe")
    run(rec, 2)
    probe.current = app("code.exe")
    run(rec, 2)
    rec.stop()
    spans, events = stored()
    # a change is attributed to the sample that observed it
    assert rel(spans) == [
        (0, 4, SpanKind.ACTIVE, "code.exe"),
        (4, 6, SpanKind.ACTIVE, "chrome.exe"),
        (6, 7, SpanKind.ACTIVE, "code.exe"),
    ]
    assert spans[0].display_name == "CODE.EXE"
    assert events == [SystemEvent.START, SystemEvent.STOP]


def test_short_blip_is_folded_into_the_previous_span(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 3)
    probe.current = app("explorer.exe")  # alt-tab passes through the shell for 0.4 s
    run(rec, 0.4, step=0.4)
    probe.current = app("code.exe")
    run(rec, 0.6, step=0.6)
    run(rec, 2)
    probe.current = app("explorer.exe")
    run(rec, 0.5, step=0.5)
    probe.current = app("chrome.exe")  # blip into a different app: still folded
    run(rec, 0.5, step=0.5)
    run(rec, 2)
    rec.stop()
    spans, _ = stored()
    durations = [(s.exe_name, s.duration_ms) for s in spans]
    assert durations == [("code.exe", 7_000), ("chrome.exe", 2_000)]
    assert spans[0].end_ms == spans[1].start_ms


def test_scheduling_gap_is_not_counted(rig, clock):
    _, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 3)
    clock.advance(600)  # suspended without any OS notification
    rec.tick()
    run(rec, 2)
    rec.stop()
    spans, events = stored()
    assert rel(spans) == [
        (0, 3, SpanKind.ACTIVE, "code.exe"),
        (603, 605, SpanKind.ACTIVE, "code.exe"),
    ]
    assert SystemEvent.GAP in events


def test_clock_jump_forward_breaks_the_span_at_the_jump(rig, clock):
    _, wall, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 3)
    wall.offset += 3_600_000  # user changed the clock (or a large NTP correction)
    run(rec, 2)
    rec.stop()
    spans, events = stored()
    assert rel(spans) == [
        (0, 3, SpanKind.ACTIVE, "code.exe"),
        (3604, 3605, SpanKind.ACTIVE, "code.exe"),
    ]
    assert SystemEvent.CLOCK_CHANGED in events


def test_clock_jump_backward_never_overlaps_recorded_time(rig, clock):
    _, wall, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 10)
    wall.offset -= 5_000 + 6_000  # back 11 s: the next 10 s of wall time are already used
    run(rec, 14)
    rec.stop()
    spans, _ = stored()
    for a, b in zip(spans, spans[1:], strict=False):
        assert a.end_ms <= b.start_ms
    assert spans[0].end_ms == T0 + 10_000
    assert sum(s.duration_ms for s in spans) < 24_000


def test_pause_reads_nothing_and_resume_starts_a_new_span(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 2)
    rec.pause()
    calls = probe.calls
    run(rec, 30)
    assert probe.calls == calls
    assert rec.status().state is RecorderState.PAUSED and rec.status().current is None
    rec.resume()
    rec.tick()
    run(rec, 2)
    rec.stop()
    spans, events = stored()
    assert rel(spans) == [
        (0, 2, SpanKind.ACTIVE, "code.exe"), (32, 34, SpanKind.ACTIVE, "code.exe")
    ]
    assert events == [
        SystemEvent.START, SystemEvent.PAUSE, SystemEvent.RESUME, SystemEvent.STOP
    ]


def test_writes_are_batched_and_a_crash_loses_at_most_one_batch(rig, clock, tmp_path):
    _, _, make, run, stored = rig
    rec = make(flush_s=10)
    rec.tick()
    run(rec, 9)
    spans, _ = stored()
    assert spans == []  # nothing written yet besides the START event
    run(rec, 1)
    spans, _ = stored()
    assert rel(spans) == [(0, 10, SpanKind.ACTIVE, "code.exe")]
    run(rec, 5)  # then the process is killed: these 5 s are never flushed
    rec._repo.conn.close()
    rec._state = RecorderState.STOPPED
    spans, _ = stored()
    assert rel(spans) == [(0, 10, SpanKind.ACTIVE, "code.exe")]

    restarted = make()
    restarted.tick()  # wall time continued, the new span starts after the stored one
    run(restarted, 2)
    restarted.stop()
    spans, _ = stored()
    assert rel(spans) == [
        (0, 10, SpanKind.ACTIVE, "code.exe"), (15, 17, SpanKind.ACTIVE, "code.exe")
    ]


def test_probe_errors_end_the_span_and_recover(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 2)
    probe.current = OSError("access denied")
    run(rec, 3)
    assert rec.status().error == "access denied"
    probe.current = app("code.exe")
    run(rec, 2)
    assert rec.status().error is None
    rec.stop()
    spans, _ = stored()
    assert rel(spans) == [(0, 2, SpanKind.ACTIVE, "code.exe"), (6, 7, SpanKind.ACTIVE, "code.exe")]


def test_locked_and_unreadable_programs(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    probe.current = app(None)  # elevated process whose name could not be read
    rec.tick()
    run(rec, 2)
    probe.current = ProbeSample(None, 0.0, locked=True)
    run(rec, 3)
    rec.stop()
    spans, _ = stored()
    assert rel(spans) == [(0, 3, SpanKind.ACTIVE, None), (3, 5, SpanKind.LOCKED, None)]


def test_failed_flush_is_retried_without_losing_spans(rig, clock, monkeypatch):
    _, _, make, run, stored = rig
    rec = make(flush_s=5)
    rec.tick()
    original = rec._repo.insert_span
    calls = {"n": 0}

    def flaky(span):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(span)

    monkeypatch.setattr(rec._repo, "insert_span", flaky)
    run(rec, 5)
    assert rec.status().error and "database is locked" in rec.status().error
    run(rec, 5)
    rec.stop()
    spans, _ = stored()
    assert rel(spans) == [(0, 10, SpanKind.ACTIVE, "code.exe")]


def test_threaded_recorder_starts_and_stops_cleanly(tmp_path):
    import threading

    probe = ScriptProbe()
    rec = ActivityRecorder(tmp_path / "t.db", probe, config=RecorderConfig(poll_s=0.05))
    rec.start()
    rec.notify("foreground")
    deadline = threading.Event()
    deadline.wait(0.3)
    rec.stop()
    assert probe.calls >= 2
    assert not [t for t in threading.enumerate() if t.name == "focuslab-recorder"]


def test_idle_is_backdated_to_the_last_input_and_return_is_recorded(rig, clock):
    probe, _, make, run, stored = rig
    rec = make(idle_threshold_s=300)
    rec.tick()
    run(rec, 60)  # typing in VS Code for a minute
    for idle in range(1, 400):  # then the user walks away for 400 s
        probe.current = app("code.exe", idle=idle)
        run(rec, 1)
    probe.current = app("code.exe", idle=0.5)  # back: input 0.5 s ago
    run(rec, 1)
    run(rec, 10)
    rec.stop()
    spans, _ = stored()
    assert [(s.kind, s.start_ms - T0, s.end_ms - T0) for s in spans] == [
        (SpanKind.ACTIVE, 0, 60_000),
        (SpanKind.IDLE, 60_000, 459_500),
        (SpanKind.ACTIVE, 459_500, 470_000),
    ]
    assert spans[1].exe_name is None  # idle time is not attributed to any program


def test_idle_threshold_can_be_changed_at_runtime(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.set_idle_threshold(60)
    probe.current = app("code.exe", idle=0)
    rec.tick()
    for idle in range(1, 71):
        probe.current = app("code.exe", idle=idle)
        run(rec, 1)
    rec.stop()
    spans, _ = stored()
    # no input since the start: all of it was idle, the empty active span is dropped
    assert [(s.kind, s.start_ms - T0) for s in spans] == [(SpanKind.IDLE, 0)]


def test_lock_notification_ends_the_span_immediately(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 5)
    clock.advance(0.3)
    rec.notify("lock")
    probe.current = ProbeSample(None, 1.0, locked=True)
    run(rec, 10)
    rec.notify("unlock")
    probe.current = app("code.exe")
    run(rec, 2)
    rec.stop()
    spans, events = stored()
    assert [(s.kind, s.start_ms - T0, s.end_ms - T0) for s in spans] == [
        (SpanKind.ACTIVE, 0, 5_300),
        (SpanKind.LOCKED, 6_300, 16_300),  # the first sample after unlock opens the next span
        (SpanKind.ACTIVE, 16_300, 17_300),
    ]
    assert SystemEvent.LOCK in events and SystemEvent.UNLOCK in events


def test_suspend_time_is_never_counted(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 5)
    rec.notify("suspend")
    spans, events = stored()
    assert events[-1] == SystemEvent.SUSPEND and spans  # flushed before the machine sleeps
    calls = probe.calls
    clock.advance(3600)  # an hour asleep; a stray tick must not sample
    rec.tick()
    assert probe.calls == calls
    rec.notify("wake")
    run(rec, 3)
    rec.stop()
    spans, events = stored()
    assert sum(s.duration_ms for s in spans) == 5_000 + 2_000  # first sample after wake: t=0
    assert SystemEvent.GAP not in events and SystemEvent.WAKE in events


def test_display_off_counts_as_idle(rig, clock):
    probe, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 5)
    rec.notify("display_off")
    probe.current = app("code.exe", idle=2)
    run(rec, 5)
    rec.notify("display_on")
    probe.current = app("code.exe", idle=0)
    run(rec, 2)
    rec.stop()
    spans, _ = stored()
    assert [s.kind for s in spans] == [SpanKind.ACTIVE, SpanKind.IDLE, SpanKind.ACTIVE]


def test_os_events_are_ignored_while_paused(rig, clock):
    _, _, make, run, stored = rig
    rec = make()
    rec.pause()
    rec.notify("lock")
    rec.notify("suspend")
    rec.stop()
    _, events = stored()
    assert events == [SystemEvent.START, SystemEvent.PAUSE, SystemEvent.STOP]


def test_unclean_shutdown_is_reported_on_next_start(rig, clock):
    _, _, make, run, stored = rig
    rec = make()
    rec.tick()
    run(rec, 10)  # flushed once
    rec._repo.conn.close()  # killed: no STOP
    rec._state = RecorderState.STOPPED
    make().stop()
    _, events = stored()
    assert events == [SystemEvent.START, SystemEvent.RECOVERED, SystemEvent.START, SystemEvent.STOP]


def test_switch_after_a_flush_persists_the_final_end(rig, clock):
    probe, _, make, run, stored = rig
    rec = make(flush_s=1)  # every tick flushes, so the closing span is already written
    rec.tick()
    run(rec, 5)
    probe.current = app("chrome.exe")
    run(rec, 3)
    rec.stop()
    spans, _ = stored()
    assert rel(spans) == [
        (0, 6, SpanKind.ACTIVE, "code.exe"), (6, 8, SpanKind.ACTIVE, "chrome.exe")
    ]


def test_browser_spans_carry_the_reported_site_only_while_fresh(rig, clock):
    from focuslab.browser.protocol import BrowserState
    from focuslab.browser.store import BrowserStateStore
    from focuslab.storage.repository import Repository

    probe, wall, make, run, stored = rig
    rec = make()
    rec.set_browser_tracking(True)
    conn = rec._repo.conn
    settings = Repository(conn)
    settings.set_setting("consent.recording", "1")
    settings.set_setting("consent.browser", "1")
    host = BrowserStateStore(conn)
    host.apply(BrowserState("chrome", "w", 1, 0, True, "github.com"), wall())
    probe.current = app("chrome.exe")
    rec.tick()
    run(rec, 5)
    host.apply(BrowserState("chrome", "w", 2, 0, True, "youtube.com"), wall())
    run(rec, 5)
    probe.current = app("code.exe")  # the browser is in the background now
    run(rec, 3)
    probe.current = app("chrome.exe")
    run(rec, 80)  # no heartbeat for 80 s: the site is no longer known
    rec.set_browser_tracking(False)
    run(rec, 2)
    rec.stop()
    spans, _ = stored()
    assert [(s.exe_name, s.domain) for s in spans] == [
        ("chrome.exe", "github.com"), ("chrome.exe", "youtube.com"), ("code.exe", None),
        ("chrome.exe", "youtube.com"), ("chrome.exe", None),
    ]
    assert [s.duration_ms // 1000 for s in spans[:3]] == [6, 5, 3]
    for a, b in zip(spans, spans[1:], strict=False):  # switches leave no holes
        assert a.end_ms == b.start_ms


def test_backdated_idle_end_is_persisted_after_a_flush(rig, clock):
    probe, _, make, run, stored = rig
    rec = make(flush_s=1, idle_threshold_s=60)  # every tick flushes
    rec.tick()
    run(rec, 10)
    for idle in range(1, 70):
        probe.current = app("code.exe", idle=idle)
        run(rec, 1)  # flushes happen while the active span is still open
    rec.stop()
    spans, _ = stored()
    assert [(s.kind, (s.end_ms - T0) // 1000) for s in spans][0] == (SpanKind.ACTIVE, 10)

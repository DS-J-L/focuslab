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

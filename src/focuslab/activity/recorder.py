"""Always-on activity recorder: turns probe samples and OS events into a span timeline.

Invariants:
- spans never overlap and never cover unobserved time (suspend, stalls, pause, not running);
- consecutive samples of the same program extend one span; blips shorter than
  ``min_span_ms`` are folded into the span before them;
- the open span is written in batches every ``flush_s`` seconds, so a crash loses at most
  one batch and never leaves a half-written row.
"""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from focuslab.domain.activity import ActivitySpan, ProbeSample, SpanKind, SystemEvent
from focuslab.domain.protocols import Clock, MonotonicClock
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.sqlite_db import connect

log = logging.getLogger(__name__)

_MAX_PENDING = 5_000  # bound memory if the database stays unwritable


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


class Probe(Protocol):
    def sample(self) -> ProbeSample: ...


class EventSource(Protocol):
    def start(self) -> bool: ...

    def stop(self) -> None: ...


EventSourceFactory = Callable[[Callable[[str], None]], EventSource]


@dataclass(frozen=True)
class RecorderConfig:
    poll_s: float = 1.0
    flush_s: float = 10.0
    max_gap_s: float = 15.0  # a longer pause between ticks is unobserved time
    clock_jump_s: float = 5.0  # wall vs monotonic disagreement that counts as a clock change
    min_span_ms: int = 1_000


class RecorderState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class RecorderStatus:
    state: RecorderState
    current: ActivitySpan | None = None
    events_hooked: bool = False
    error: str | None = None


@dataclass(eq=False)  # identity: two spans with equal fields are still different rows
class _Span:
    start_ms: int
    end_ms: int
    kind: SpanKind
    exe_name: str | None
    display_name: str | None
    span_id: int | None = None

    def same(self, kind: SpanKind, exe_name: str | None) -> bool:
        return self.kind is kind and self.exe_name == exe_name

    def frozen(self) -> ActivitySpan:
        return ActivitySpan(
            self.start_ms, self.end_ms, self.kind, self.exe_name, self.display_name, self.span_id
        )


class ActivityRecorder:
    """Thread-safe. ``start`` opens its own database connection and, by default, a poll thread."""

    def __init__(
        self,
        db_path: Path | str,
        probe: Probe,
        *,
        clock: Clock | None = None,
        wall: Callable[[], int] = wall_ms,
        config: RecorderConfig | None = None,
        events: EventSourceFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._probe = probe
        self._clock = clock or MonotonicClock()
        self._wall = wall
        self._cfg = config or RecorderConfig()
        self._events_factory = events
        self._events: EventSource | None = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._repo: ActivityRepository | None = None
        self._state = RecorderState.STOPPED
        self._error: str | None = None
        self._reset_timeline()

    def _reset_timeline(self) -> None:
        self._open: _Span | None = None
        self._prev: _Span | None = None  # last closed span, for folding blips
        self._dirty: list[_Span] = []
        self._deleted: list[int] = []
        self._pending_events: list[tuple[int, str, str | None]] = []
        self._last_mono: int | None = None
        self._last_wall = 0
        self._last_flush_mono = self._clock.monotonic_ms()
        self._floor_ms = 0  # nothing may be recorded before this (no overlaps after clock changes)

    # lifecycle ------------------------------------------------------------------
    @property
    def state(self) -> RecorderState:
        return self._state

    def start(self, run_thread: bool = True) -> None:
        with self._lock:
            if self._state is not RecorderState.STOPPED:
                return
            self._repo = ActivityRepository(connect(self._db_path, check_same_thread=False))
            self._reset_timeline()
            last = self._repo.last_span()
            self._floor_ms = last.end_ms if last else 0
            self._state = RecorderState.RUNNING
            self._event(SystemEvent.START)
            self._flush_locked()
        if run_thread:
            self._stop.clear()
            self._wake.set()  # first sample right away
            self._thread = threading.Thread(target=self._run, name="focuslab-recorder", daemon=True)
            self._thread.start()
            if self._events_factory:
                self._events = self._events_factory(self.notify)
                self._events.start()

    def stop(self) -> None:
        events, self._events = self._events, None
        if events:
            events.stop()
        self._stop.set()
        self._wake.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            if self._state is RecorderState.STOPPED:
                return
            self._close_open()
            self._event(SystemEvent.STOP)
            self._flush_locked()
            self._repo.conn.close()
            self._repo = None
            self._state = RecorderState.STOPPED

    def pause(self) -> None:
        """Stop observing: nothing is read from the OS until ``resume``."""
        with self._lock:
            if self._state is not RecorderState.RUNNING:
                return
            self._close_open()
            self._event(SystemEvent.PAUSE)
            self._flush_locked()
            self._state = RecorderState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self._state is not RecorderState.PAUSED:
                return
            self._state = RecorderState.RUNNING
            self._last_mono = None
            self._prev = None
            self._event(SystemEvent.RESUME)
        self._wake.set()

    def notify(self, name: str) -> None:
        """Called from OS event threads; a foreground change is sampled right away."""
        self._wake.set()

    def status(self) -> RecorderStatus:
        with self._lock:
            return RecorderStatus(
                self._state,
                self._open.frozen() if self._open else None,
                bool(self._events and getattr(self._events, "running", False)),
                self._error,
            )

    # ticking --------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._cfg.poll_s)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.tick()
            except Exception:
                log.exception("activity tick failed")

    def tick(self) -> None:
        with self._lock:
            if self._state is not RecorderState.RUNNING:
                return
            mono, wall = self._clock.monotonic_ms(), self._wall()
            self._check_continuity(mono, wall)
            try:
                sample: ProbeSample | None = self._probe.sample()
                self._error = None
            except Exception as exc:  # OS errors end the span; time stays unobserved
                if str(exc) != self._error:
                    log.warning("activity probe failed: %s", exc)
                self._error = str(exc)
                sample = None
            self._observe(sample, wall)
            self._last_mono, self._last_wall = mono, wall
            if mono - self._last_flush_mono >= self._cfg.flush_s * 1000:
                self._flush_locked()

    def _check_continuity(self, mono: int, wall: int) -> None:
        if self._last_mono is None:
            return
        d_mono, d_wall = mono - self._last_mono, wall - self._last_wall
        if d_mono > self._cfg.max_gap_s * 1000:
            self._break_timeline(SystemEvent.GAP, d_mono)
        elif abs(d_wall - d_mono) > self._cfg.clock_jump_s * 1000:
            self._break_timeline(SystemEvent.CLOCK_CHANGED, d_wall - d_mono)

    def _break_timeline(self, event: SystemEvent, delta_ms: int) -> None:
        self._close_open()
        self._prev = None
        self._event(event, str(round(delta_ms / 1000)))

    def _observe(self, sample: ProbeSample | None, wall: int) -> None:
        if sample is None or wall < self._floor_ms:
            self._close_open()
            return
        kind = SpanKind.LOCKED if sample.locked else SpanKind.ACTIVE
        app = sample.app if kind is SpanKind.ACTIVE else None
        exe = app.exe_name if app else None
        span = self._open
        if span and span.same(kind, exe):
            span.end_ms = max(span.end_ms, wall)
            self._mark(span)
            return
        if span:
            self._close(wall)
        prev = self._prev
        if prev and prev.end_ms == wall and prev.same(kind, exe):
            self._open, self._prev = prev, None  # A, short blip, A -> one span of A
            return
        self._open = _Span(wall, wall, kind, exe, app.display_name if app else None)
        self._mark(self._open)

    def _close_open(self) -> None:
        if self._open:
            self._close(self._open.end_ms)

    def _close(self, end_ms: int) -> None:
        span, self._open = self._open, None
        span.end_ms = max(span.start_ms, end_ms)
        self._floor_ms = max(self._floor_ms, span.end_ms)
        prev = self._prev
        if span.end_ms - span.start_ms < self._cfg.min_span_ms and prev and (
            prev.end_ms == span.start_ms
        ):
            prev.end_ms = span.end_ms
            self._mark(prev)
            if span in self._dirty:
                self._dirty.remove(span)
            if span.span_id is not None:
                self._deleted.append(span.span_id)
            span = prev
        elif span.end_ms == span.start_ms:  # zero-length: nothing to keep
            if span in self._dirty:
                self._dirty.remove(span)
            if span.span_id is not None:
                self._deleted.append(span.span_id)
            return
        self._prev = span

    def _mark(self, span: _Span) -> None:
        if span not in self._dirty:
            self._dirty.append(span)
            del self._dirty[:-_MAX_PENDING]

    def _event(self, event: SystemEvent, detail: str | None = None) -> None:
        self._pending_events.append((self._wall(), event.value, detail))
        del self._pending_events[:-_MAX_PENDING]

    # persistence ----------------------------------------------------------------
    def flush(self) -> None:
        with self._lock:
            if self._repo is not None:
                self._flush_locked()

    def _flush_locked(self) -> None:
        self._last_flush_mono = self._clock.monotonic_ms()
        dirty = [s for s in self._dirty if s.end_ms > s.start_ms or s is self._open]
        if not (dirty or self._deleted or self._pending_events):
            return
        inserted: list[_Span] = []
        repo = self._repo
        try:
            with repo.transaction():
                for span_id in self._deleted:
                    repo.conn.execute("DELETE FROM activity_span WHERE id = ?", (span_id,))
                for span in dirty:
                    if span.span_id is None:
                        span.span_id = repo.insert_span(span.frozen())
                        inserted.append(span)
                    else:
                        repo.update_span_end(span.span_id, span.end_ms)
                repo.add_events(self._pending_events)
        except sqlite3.Error as exc:
            for span in inserted:  # those ids were rolled back
                span.span_id = None
            log.warning("activity flush failed, will retry: %s", exc)
            self._error = f"저장 실패: {exc}"
            return
        self._dirty.clear()
        self._deleted.clear()
        self._pending_events.clear()

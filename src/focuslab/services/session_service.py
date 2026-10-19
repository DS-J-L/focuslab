"""Session lifecycle (IDLE -> RUNNING <-> PAUSED -> FINISHED) and the 1-second runner.

Every second while RUNNING the service fuses the latest observations, asks the
rule engine for a decision and stores one ``state_sample`` plus the open state
segment. Pausing releases the camera; seconds while paused are not observed.
"""

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

from focuslab.camera.calibration import Calibration
from focuslab.config import RULE_VERSION, RuleConfig
from focuslab.domain.events import StateSegment
from focuslab.domain.models import (
    ActivityObservation,
    CameraStatus,
    Decision,
    FaceObservation,
    FocusState,
    SessionConfig,
    SessionStatus,
    StateSample,
)
from focuslab.domain.protocols import ActivitySource, Clock, FaceSource, MonotonicClock
from focuslab.focus.fusion import FaceEvidence, fuse
from focuslab.focus.reasons import Reason
from focuslab.focus.rules import RuleEngine
from focuslab.storage.repository import Repository, utc_now
from focuslab.storage.sqlite_db import connect

log = logging.getLogger(__name__)

_MAX_SEGMENT_APPS = 10


class Lifecycle(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"


class InvalidTransition(RuntimeError):
    pass


_TRANSITIONS = {
    ("start", Lifecycle.IDLE): Lifecycle.RUNNING,
    ("pause", Lifecycle.RUNNING): Lifecycle.PAUSED,
    ("resume", Lifecycle.PAUSED): Lifecycle.RUNNING,
    ("finish", Lifecycle.RUNNING): Lifecycle.FINISHED,
    ("finish", Lifecycle.PAUSED): Lifecycle.FINISHED,
}


class SessionLifecycle:
    def __init__(self) -> None:
        self.state = Lifecycle.IDLE

    def can(self, action: str) -> bool:
        return (action, self.state) in _TRANSITIONS

    def apply(self, action: str) -> Lifecycle:
        try:
            self.state = _TRANSITIONS[(action, self.state)]
        except KeyError:
            raise InvalidTransition(f"cannot {action} while {self.state}") from None
        return self.state


@dataclass(frozen=True)
class LiveSnapshot:
    lifecycle: Lifecycle = Lifecycle.IDLE
    session_id: int | None = None
    config: SessionConfig | None = None
    active_s: int = 0
    paused_s: int = 0
    on_break: bool = False
    decision: Decision | None = None
    app_name: str | None = None
    idle_s: float | None = None
    camera_status: CameraStatus = CameraStatus.OFF
    face_evidence: FaceEvidence | None = None
    face: FaceObservation | None = None
    seconds: dict[FocusState, int] = field(default_factory=dict)
    segments: tuple[StateSegment, ...] = ()
    planned_reached: bool = False


FaceFactory = Callable[[SessionConfig], FaceSource | None]
ActivityFactory = Callable[[SessionConfig], ActivitySource]


class SessionService:
    """Thread-safe orchestration used by the UI. One session at a time."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        face_factory: FaceFactory,
        activity_factory: ActivityFactory,
        clock: Clock | None = None,
        rule_config: RuleConfig | None = None,
        calibration: Callable[[], Calibration] = Calibration,
        auto_tick: bool = True,
    ) -> None:
        self._repo = Repository(connect(db_path, check_same_thread=False))
        self._face_factory = face_factory
        self._activity_factory = activity_factory
        self._clock = clock or MonotonicClock()
        self._cfg = rule_config or RuleConfig()
        self._calibration_provider = calibration
        self._auto_tick = auto_tick
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reset()

    def _reset(self) -> None:
        self._lifecycle = SessionLifecycle()
        self._session_id: int | None = None
        self._config: SessionConfig | None = None
        self._engine: RuleEngine | None = None
        self._face: FaceSource | None = None
        self._activity: ActivitySource | None = None
        self._calibration = Calibration()
        self._active_s = 0
        self._paused_s = 0
        self._pause_started_ms: int | None = None
        self._last_tick_ms = 0
        self._on_break = False
        self._counts: Counter[FocusState] = Counter()
        self._segments: list[StateSegment] = []
        self._open_segment: StateSegment | None = None
        self._last_decision: Decision | None = None
        self._last_activity: ActivityObservation | None = None
        self._last_face: FaceObservation | None = None
        self._last_face_evidence: FaceEvidence | None = None
        self._planned_reached = False

    @property
    def repository(self) -> Repository:
        """Shared repository; callers on other threads must hold ``lock``."""
        return self._repo

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def face_source(self) -> FaceSource | None:
        """The live session's camera source (for the in-memory preview), if any."""
        return self._face

    # lifecycle ------------------------------------------------------------------
    def start(self, config: SessionConfig) -> int:
        self._join_runner()  # a runner that auto-finished may still be exiting
        with self._lock:
            if self._lifecycle.state is Lifecycle.FINISHED:
                self._reset()
            self._lifecycle.apply("start")
            self._config = config
            self._session_id = self._repo.create_session(config, RULE_VERSION)
            self._engine = RuleEngine(config.mode, self._cfg)
            self._calibration = self._calibration_provider()
            self._activity = self._activity_factory(config)
            self._face = self._face_factory(config) if config.camera_enabled else None
            self._start_face()
            self._last_tick_ms = self._clock.monotonic_ms()
            session_id = self._session_id
        if self._auto_tick:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="focuslab-session", daemon=True)
            self._thread.start()
        return session_id

    def pause(self) -> None:
        with self._lock:
            self._lifecycle.apply("pause")
            self._stop_face()
            self._pause_started_ms = self._clock.monotonic_ms()
            self._open_segment = None
            self._repo.set_status(self._session_id, SessionStatus.PAUSED)

    def resume(self) -> None:
        with self._lock:
            self._lifecycle.apply("resume")
            self._close_pause()
            self._repo.set_status(self._session_id, SessionStatus.RUNNING)
            self._engine.reset()
            self._start_face()
            self._last_tick_ms = self._clock.monotonic_ms()

    def set_break(self, on: bool) -> None:
        with self._lock:
            if self._lifecycle.state is not Lifecycle.RUNNING:
                raise InvalidTransition("break is only available while running")
            self._on_break = on

    def finish(self) -> int | None:
        """Stop observing and close the session. Returns the finished session id."""
        with self._lock:
            session_id = self._finish_locked()
        self._join_runner()
        return session_id

    def _finish_locked(self) -> int | None:
        if not self._lifecycle.can("finish"):
            return None
        self._lifecycle.apply("finish")
        self._stop_face()
        self._close_pause()
        self._repo.set_status(self._session_id, SessionStatus.FINISHED, utc_now())
        self._open_segment = None
        return self._session_id

    def _close_pause(self) -> None:
        if self._pause_started_ms is None:
            return
        seconds = round((self._clock.monotonic_ms() - self._pause_started_ms) / 1000)
        self._pause_started_ms = None
        self._paused_s += seconds
        self._repo.add_paused_seconds(self._session_id, seconds)

    def set_self_report(self, session_id: int, value: str | None) -> None:
        with self._lock:
            self._repo.set_self_report(session_id, value)

    def correct_current(self, label: FocusState) -> bool:
        """Correct the latest state segment of the live session (the user's data only)."""
        with self._lock:
            if not self._segments or self._segments[-1].event_id is None:
                return False
            seg = self._segments[-1]
            self._repo.set_feedback(seg.event_id, label, "live")
            self._segments[-1] = replace(seg, corrected_label=label)
            if self._open_segment and self._open_segment.event_id == seg.event_id:
                self._open_segment = self._segments[-1]
            return True

    def shutdown(self) -> None:
        self.finish()
        with self._lock:
            self._repo.conn.close()

    # sensors --------------------------------------------------------------------
    def _start_face(self) -> None:
        if self._face is None:
            return
        try:
            self._face.start()
        except Exception:
            log.warning("camera start failed; continuing with PC activity only", exc_info=True)

    def _stop_face(self) -> None:
        if self._face is None:
            return
        try:
            self._face.stop()
        except Exception:
            log.warning("camera stop failed", exc_info=True)

    # ticking --------------------------------------------------------------------
    def _run(self) -> None:
        # Absolute schedule, so the time spent in tick() never delays later ticks.
        next_at = time.monotonic() + 1.0
        while not self._stop.wait(max(0.0, next_at - time.monotonic())):
            next_at += 1.0
            try:
                self.tick()
            except Exception:
                log.exception("session tick failed")
            if self._lifecycle.state is Lifecycle.FINISHED:
                break

    def _join_runner(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def tick(self) -> Decision | None:
        """Evaluate one second. Long gaps (sleep, stalls) are stored as UNKNOWN."""
        with self._lock:
            if self._lifecycle.state is not Lifecycle.RUNNING:
                return None
            now = self._clock.monotonic_ms()
            elapsed = round((now - self._last_tick_ms) / 1000)
            if elapsed <= 0:
                return self._last_decision
            # Advance in whole seconds so scheduling jitter never accumulates.
            self._last_tick_ms += elapsed * 1000
            if elapsed > 2:
                self._fill_gap(elapsed - 1)
                elapsed = 1

            config = self._config
            face = self._face.latest() if self._face else None
            camera_status = self._face.status if self._face else CameraStatus.OFF
            activity = self._activity.sample(now)
            frame = fuse(
                now, face, activity,
                camera_enabled=config.camera_enabled,
                camera_status=camera_status,
                calibration=self._calibration,
                cfg=self._cfg,
                user_break=self._on_break,
            )
            decision = self._engine.evaluate(frame, dt_s=elapsed)
            if config.planned_minutes:
                elapsed = min(elapsed, config.planned_minutes * 60 - self._active_s)
            for _ in range(elapsed):  # a tick one second late covers both seconds
                self._record(
                    StateSample(
                        self._active_s, decision.state, decision.confidence,
                        decision.reason_codes, frame.app_name,
                    )
                )
            self._last_decision = decision
            self._last_activity = activity
            self._last_face = face
            self._last_face_evidence = frame.face
            if config.planned_minutes and self._active_s >= config.planned_minutes * 60:
                self._planned_reached = True
                self._finish_locked()
            return decision

    def _fill_gap(self, seconds: int) -> None:
        observed = min(seconds, self._cfg.max_gap_fill_s)
        for _ in range(observed):
            self._record(
                StateSample(self._active_s, FocusState.UNKNOWN, 0.0, (Reason.OBSERVATION_GAP,))
            )
        if seconds > observed:  # very long suspend: count it as paused, not observed
            self._paused_s += seconds - observed
            self._repo.add_paused_seconds(self._session_id, seconds - observed)
        self._engine.reset()

    def _record(self, sample: StateSample) -> None:
        self._repo.add_sample(self._session_id, sample)
        self._counts[sample.state] += 1
        self._active_s = sample.second_offset + 1
        seg = self._open_segment
        app = sample.app_name
        if seg and seg.state == sample.state and seg.end_s == sample.second_offset:
            apps = seg.app_names
            if app and app not in apps and len(apps) < _MAX_SEGMENT_APPS:
                apps = (*apps, app)
            seg = replace(seg, end_s=seg.end_s + 1, app_names=apps)
            self._repo.extend_segment(seg.event_id, seg.end_s, seg.app_names)
            self._segments[-1] = seg
        else:
            seg = StateSegment(
                sample.second_offset, sample.second_offset + 1, sample.state,
                sample.reason_codes, (app,) if app else (),
            )
            event_id = self._repo.insert_segment(self._session_id, seg, RULE_VERSION)
            seg = replace(seg, event_id=event_id)
            self._segments.append(seg)
        self._open_segment = seg

    # snapshot -------------------------------------------------------------------
    def snapshot(self) -> LiveSnapshot:
        with self._lock:
            paused = self._paused_s
            if self._pause_started_ms is not None:
                paused += round((self._clock.monotonic_ms() - self._pause_started_ms) / 1000)
            activity = self._last_activity
            return LiveSnapshot(
                lifecycle=self._lifecycle.state,
                session_id=self._session_id,
                config=self._config,
                active_s=self._active_s,
                paused_s=paused,
                on_break=self._on_break,
                decision=self._last_decision,
                app_name=activity.process_name if activity else None,
                idle_s=activity.idle_seconds if activity else None,
                camera_status=self._face.status if self._face else CameraStatus.OFF,
                face_evidence=self._last_face_evidence,
                face=self._last_face,
                seconds=dict(self._counts),
                segments=tuple(self._segments),
                planned_reached=self._planned_reached,
            )

    def recover_interrupted(self) -> list[int]:
        with self._lock:
            return self._repo.recover_interrupted()


"""Scripted sensors for tests and ``focuslab --demo``. They never open a camera or read the OS."""

from collections.abc import Sequence

from focuslab.activity.windows_tracker import allowed_status
from focuslab.domain.models import ActivityObservation, CameraStatus, FaceObservation
from focuslab.domain.protocols import Clock, MonotonicClock

# kind -> (face_visible, yaw_deg, pitch_deg, quality)
FACE_POSES = {
    "forward": (True, 2.0, -3.0, 0.9),
    "down": (True, 0.0, -35.0, 0.8),
    "away": (True, 45.0, 0.0, 0.8),
    "absent": (False, None, None, 0.8),
    "dark": (True, 0.0, 0.0, 0.1),
    "error": (None, None, None, None),
}

DEMO_FACE_SCRIPT = (
    (40, "forward"), (8, "down"), (20, "away"), (30, "forward"), (25, "absent"), (30, "forward"),
)
DEMO_ACTIVITY_SCRIPT = (
    (45, "code.exe", "active"), (10, "chrome.exe", "active"), (25, "KakaoTalk.exe", "idle"),
    (30, "code.exe", "active"), (30, "code.exe", "idle"), (15, "code.exe", "active"),
)


def _position(script_len: float, elapsed_s: float, loop: bool) -> float:
    if loop and script_len > 0:
        return elapsed_s % script_len
    return min(elapsed_s, max(script_len - 1e-6, 0))


class MockFaceSource:
    """Plays ``(seconds, kind)`` steps from ``FACE_POSES`` relative to ``start()``."""

    def __init__(
        self,
        script: Sequence[tuple[float, str]] = DEMO_FACE_SCRIPT,
        clock: Clock | None = None,
        loop: bool = True,
    ) -> None:
        self._script = tuple(script)
        self._clock = clock or MonotonicClock()
        self._loop = loop
        self._t0: int | None = None
        self.start_count = 0
        self.stop_count = 0

    @property
    def status(self) -> CameraStatus:
        return CameraStatus.OFF if self._t0 is None else CameraStatus.RUNNING

    def start(self) -> None:
        self._t0 = self._clock.monotonic_ms()
        self.start_count += 1

    def stop(self) -> None:
        self._t0 = None
        self.stop_count += 1

    def latest(self) -> FaceObservation | None:
        if self._t0 is None:
            return None
        now = self._clock.monotonic_ms()
        pos = _position(sum(d for d, _ in self._script), (now - self._t0) / 1000, self._loop)
        kind = self._script[-1][1]
        for duration, step_kind in self._script:
            if pos < duration:
                kind = step_kind
                break
            pos -= duration
        visible, yaw, pitch, quality = FACE_POSES[kind]
        return FaceObservation(now, visible, yaw, pitch, quality)


class MockActivitySource:
    """Plays ``(seconds, process_name, "active" | "idle" | "locked" | "unavailable")`` steps.

    A step may add ``domain`` and ``page_title`` as if the browser extension reported them.
    """

    def __init__(
        self,
        allowed_apps: Sequence[str],
        script: Sequence[tuple] = DEMO_ACTIVITY_SCRIPT,
        loop: bool = True,
    ) -> None:
        self._allowed = tuple(allowed_apps)
        self._script = tuple(script)
        self._loop = loop
        self._t0: int | None = None

    def sample(self, now_ms: int) -> ActivityObservation:
        if self._t0 is None:
            self._t0 = now_ms
        pos = _position(sum(s[0] for s in self._script), (now_ms - self._t0) / 1000, self._loop)
        step = self._script[-1]
        for candidate in self._script:
            if pos < candidate[0]:
                step = candidate
                break
            pos -= candidate[0]
        _, name, kind, domain, title = (*step, None, None)[:5]
        if kind == "unavailable":
            return ActivityObservation(now_ms, None, None, None, available=False)
        idle = pos if kind == "idle" else 0.0
        return ActivityObservation(
            now_ms, name, allowed_status(name, self._allowed, domain), idle, available=True,
            screen_locked=kind == "locked", domain=domain, page_title=title,
        )

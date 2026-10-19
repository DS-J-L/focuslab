"""Sensor and clock interfaces. Sensors publish observations; they never decide states."""

import time
from typing import Protocol

from focuslab.domain.models import ActivityObservation, CameraStatus, FaceObservation


class Clock(Protocol):
    def monotonic_ms(self) -> int: ...


class MonotonicClock:
    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


class FaceSource(Protocol):
    """Camera + face pipeline. ``start``/``stop`` must acquire/release the device."""

    @property
    def status(self) -> CameraStatus: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest(self) -> FaceObservation | None: ...


class ActivitySource(Protocol):
    """Foreground app and OS idle time, sampled on the session tick."""

    def sample(self, now_ms: int) -> ActivityObservation: ...

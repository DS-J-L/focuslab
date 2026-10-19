"""Initial observation contracts from the development plan.

Timestamps use a monotonic session clock. Missing observations are unknown,
not evidence that someone is distracted or absent.
"""

from dataclasses import dataclass
from enum import StrEnum


class FocusState(StrEnum):
    """Observable work-pattern estimates, never medical or attention diagnoses."""

    ON_TASK = "ON_TASK"
    POSSIBLY_OFF_TASK = "POSSIBLY_OFF_TASK"
    AWAY = "AWAY"
    BREAK = "BREAK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FaceObservation:
    """Ephemeral derived observation; no frame or biometric identity is stored."""

    timestamp_ms: int
    face_visible: bool | None
    yaw_deg: float | None
    pitch_deg: float | None
    eye_closed_signal: float | None
    quality: float | None


@dataclass(frozen=True)
class ActivityObservation:
    """Minimal activity observation without window titles or keystrokes."""

    timestamp_ms: int
    process_name: str | None
    is_allowed_app: bool | None
    idle_seconds: float | None
    available: bool

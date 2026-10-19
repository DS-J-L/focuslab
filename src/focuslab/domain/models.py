"""Observation, session and decision contracts shared by sensors, rules, storage and UI.

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


class SessionMode(StrEnum):
    """Work modes change which observations count as normal work."""

    CODING = "CODING"
    LECTURE = "LECTURE"
    READING_WRITING = "READING_WRITING"
    CUSTOM = "CUSTOM"


class SessionStatus(StrEnum):
    """Persisted lifecycle status. INTERRUPTED marks sessions recovered after a crash."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    INTERRUPTED = "INTERRUPTED"


class CameraStatus(StrEnum):
    """Camera pipeline health as shown to the user; anything but RUNNING means UNKNOWN."""

    OFF = "OFF"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    NO_DEVICE = "NO_DEVICE"
    DISCONNECTED = "DISCONNECTED"
    MODEL_MISSING = "MODEL_MISSING"
    MODEL_ERROR = "MODEL_ERROR"


class HeadDirection(StrEnum):
    FORWARD = "FORWARD"
    DOWN = "DOWN"
    AWAY = "AWAY"


@dataclass(frozen=True)
class FaceObservation:
    """Ephemeral derived observation; no frame or biometric identity is stored.

    Angles are relative to the user's calibrated forward pose. Positive pitch looks up,
    negative pitch looks down.
    """

    timestamp_ms: int
    face_visible: bool | None
    yaw_deg: float | None
    pitch_deg: float | None
    quality: float | None


@dataclass(frozen=True)
class ActivityObservation:
    """Minimal activity observation without window titles or keystrokes.

    ``is_allowed_app`` is None when the foreground app is neutral (desktop shell,
    FocusLab itself) or unavailable.
    """

    timestamp_ms: int
    process_name: str | None
    is_allowed_app: bool | None
    idle_seconds: float | None
    available: bool
    screen_locked: bool = False
    domain: str | None = None  # browser site from the extension, if known


@dataclass(frozen=True)
class SessionConfig:
    goal: str
    mode: SessionMode
    planned_minutes: int
    allowed_apps: tuple[str, ...]
    camera_enabled: bool


@dataclass(frozen=True)
class Decision:
    """Rule engine output for one second, with the reasons a user can inspect."""

    state: FocusState
    confidence: float
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StateSample:
    second_offset: int
    state: FocusState
    confidence: float
    reason_codes: tuple[str, ...] = ()
    app_name: str | None = None
    at_ms: int | None = None  # UTC epoch ms of this second (None for gap fills, pre-v5 rows)


@dataclass(frozen=True)
class SessionRecord:
    id: int
    goal: str
    mode: SessionMode
    planned_minutes: int
    started_at_utc: str
    ended_at_utc: str | None
    status: SessionStatus
    camera_enabled: bool
    rule_version: str
    paused_seconds: int = 0
    self_report: str | None = None
    allowed_apps: tuple[str, ...] = ()

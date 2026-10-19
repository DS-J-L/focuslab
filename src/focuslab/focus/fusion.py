"""Merge the latest face and activity observations into one per-second frame.

Each observation has a TTL; an expired observation becomes UNKNOWN instead of
silently repeating the last value.
"""

from dataclasses import dataclass
from enum import StrEnum

from focuslab.activity.windows_tracker import normalize
from focuslab.camera.calibration import Calibration
from focuslab.config import BROWSERS, RuleConfig
from focuslab.domain.models import (
    ActivityObservation,
    CameraStatus,
    FaceObservation,
)
from focuslab.focus.reasons import Reason


class AppRelation(StrEnum):
    ALLOWED = "ALLOWED"
    UNRELATED = "UNRELATED"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class FaceEvidence(StrEnum):
    FORWARD = "FORWARD"
    DOWN = "DOWN"
    AWAY = "AWAY"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    OFF = "OFF"


@dataclass(frozen=True)
class FusedFrame:
    now_ms: int
    app: AppRelation
    face: FaceEvidence
    app_name: str | None = None
    idle_s: float | None = None
    reasons: tuple[str, ...] = ()  # why an input is missing or unreliable
    screen_locked: bool = False
    user_break: bool = False
    is_browser: bool = False


def _activity(
    now_ms: int, obs: ActivityObservation | None, cfg: RuleConfig
) -> tuple[AppRelation, str | None]:
    if obs is None or not obs.available:
        return AppRelation.UNKNOWN, Reason.ACTIVITY_UNAVAILABLE
    if now_ms - obs.timestamp_ms > cfg.activity_ttl_ms:
        return AppRelation.UNKNOWN, Reason.ACTIVITY_STALE
    if obs.is_allowed_app is None:
        return AppRelation.NEUTRAL, None
    return (AppRelation.ALLOWED if obs.is_allowed_app else AppRelation.UNRELATED), None


def _face(
    now_ms: int,
    obs: FaceObservation | None,
    camera_enabled: bool,
    camera_status: CameraStatus,
    calibration: Calibration,
    cfg: RuleConfig,
) -> tuple[FaceEvidence, str | None]:
    if not camera_enabled:
        return FaceEvidence.OFF, Reason.CAMERA_OFF
    if camera_status is not CameraStatus.RUNNING:
        return FaceEvidence.UNKNOWN, Reason.CAMERA_UNAVAILABLE
    if obs is None or now_ms - obs.timestamp_ms > cfg.face_ttl_ms:
        return FaceEvidence.UNKNOWN, Reason.FACE_STALE
    if obs.face_visible is None:
        return FaceEvidence.UNKNOWN, Reason.CAMERA_UNAVAILABLE
    if obs.quality is not None and obs.quality < cfg.min_face_quality:
        return FaceEvidence.UNKNOWN, Reason.FACE_LOW_QUALITY
    if not obs.face_visible:
        return FaceEvidence.ABSENT, None
    if obs.yaw_deg is None or obs.pitch_deg is None:
        return FaceEvidence.UNKNOWN, Reason.FACE_LOW_QUALITY
    direction = calibration.classify(obs.yaw_deg, obs.pitch_deg)
    return FaceEvidence(direction.value), None


def fuse(
    now_ms: int,
    face: FaceObservation | None,
    activity: ActivityObservation | None,
    *,
    camera_enabled: bool,
    camera_status: CameraStatus = CameraStatus.RUNNING,
    calibration: Calibration | None = None,
    cfg: RuleConfig | None = None,
    user_break: bool = False,
) -> FusedFrame:
    cfg = cfg or RuleConfig()
    app, app_reason = _activity(now_ms, activity, cfg)
    face_ev, face_reason = _face(
        now_ms, face, camera_enabled, camera_status, calibration or Calibration(), cfg
    )
    fresh = app is not AppRelation.UNKNOWN
    name = activity.process_name if activity and fresh else None
    return FusedFrame(
        now_ms=now_ms,
        app=app,
        face=face_ev,
        app_name=name,
        idle_s=activity.idle_seconds if activity and fresh else None,
        reasons=tuple(r for r in (app_reason, face_reason) if r),
        screen_locked=bool(activity and fresh and activity.screen_locked),
        user_break=user_break,
        is_browser=bool(name and normalize(name) in BROWSERS),
    )

"""Reason codes attached to every decision, with the wording shown to users."""

from enum import StrEnum

from focuslab.i18n import LocalizedMapping


class Reason(StrEnum):
    USER_BREAK = "USER_BREAK"
    SCREEN_LOCKED = "SCREEN_LOCKED"
    OBSERVATION_GAP = "OBSERVATION_GAP"
    ALLOWED_APP = "ALLOWED_APP"
    UNRELATED_APP = "UNRELATED_APP"
    NEUTRAL_APP = "NEUTRAL_APP"
    BROWSER_DETAIL_UNKNOWN = "BROWSER_DETAIL_UNKNOWN"
    ACTIVITY_UNAVAILABLE = "ACTIVITY_UNAVAILABLE"
    ACTIVITY_STALE = "ACTIVITY_STALE"
    USER_ACTIVE = "USER_ACTIVE"
    USER_IDLE = "USER_IDLE"
    IDLE_EXPECTED_IN_MODE = "IDLE_EXPECTED_IN_MODE"
    CAMERA_OFF = "CAMERA_OFF"
    CAMERA_UNAVAILABLE = "CAMERA_UNAVAILABLE"
    FACE_STALE = "FACE_STALE"
    FACE_LOW_QUALITY = "FACE_LOW_QUALITY"
    FACE_FORWARD = "FACE_FORWARD"
    HEAD_DOWN = "HEAD_DOWN"
    HEAD_DOWN_READING = "HEAD_DOWN_READING"
    HEAD_TURNED_AWAY = "HEAD_TURNED_AWAY"
    FACE_NOT_VISIBLE = "FACE_NOT_VISIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HYSTERESIS_HOLD = "HYSTERESIS_HOLD"


REASON_TEXT = LocalizedMapping(
    {
        Reason.USER_BREAK: "You started a break",
        Reason.SCREEN_LOCKED: "Screen locked (observation unavailable)",
        Reason.OBSERVATION_GAP: "Observation interrupted by sleep or delay",
        Reason.ALLOWED_APP: "Using an allowed app",
        Reason.UNRELATED_APP: "App is not on the allow list",
        Reason.NEUTRAL_APP: "Neutral app (desktop, FocusLab, etc.)",
        Reason.BROWSER_DETAIL_UNKNOWN: "Browser activity details unavailable",
        Reason.ACTIVITY_UNAVAILABLE: "PC activity unavailable",
        Reason.ACTIVITY_STALE: "PC activity observation is stale",
        Reason.USER_ACTIVE: "Keyboard or mouse input detected",
        Reason.USER_IDLE: "No keyboard or mouse input",
        Reason.IDLE_EXPECTED_IN_MODE: "No input is expected in this mode",
        Reason.CAMERA_OFF: "Camera not in use",
        Reason.CAMERA_UNAVAILABLE: "Camera unavailable",
        Reason.FACE_STALE: "Face observation is stale",
        Reason.FACE_LOW_QUALITY: "Low-quality face observation (dark, obscured, or distant)",
        Reason.FACE_FORWARD: "Observed facing the screen",
        Reason.HEAD_DOWN: "Looking down (does not establish task deviation)",
        Reason.HEAD_DOWN_READING: "Looking down (reading / writing mode)",
        Reason.HEAD_TURNED_AWAY: "Looking away from the screen",
        Reason.FACE_NOT_VISIBLE: "Face not visible to the camera",
        Reason.INSUFFICIENT_EVIDENCE: "Insufficient evidence",
        Reason.HYSTERESIS_HOLD: "Brief change; holding the previous state",
    }
)


def describe(codes: tuple[str, ...] | list[str]) -> list[str]:
    return [REASON_TEXT.get(code, code) for code in codes]  # type: ignore[call-overload]

"""Reason codes attached to every decision, with the wording shown to users."""

from enum import StrEnum


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


REASON_TEXT = {
    Reason.USER_BREAK: "사용자가 휴식을 시작함",
    Reason.SCREEN_LOCKED: "화면 잠금 중 (관찰 불가)",
    Reason.OBSERVATION_GAP: "절전·지연으로 관찰이 끊긴 구간",
    Reason.ALLOWED_APP: "허용 앱 사용 중",
    Reason.UNRELATED_APP: "허용 목록에 없는 앱",
    Reason.NEUTRAL_APP: "중립 앱(바탕화면·FocusLab 등)",
    Reason.BROWSER_DETAIL_UNKNOWN: "브라우저 세부 활동 미확인",
    Reason.ACTIVITY_UNAVAILABLE: "PC 활동 정보 없음",
    Reason.ACTIVITY_STALE: "PC 활동 정보가 오래됨",
    Reason.USER_ACTIVE: "키보드·마우스 입력 있음",
    Reason.USER_IDLE: "키보드·마우스 입력 없음",
    Reason.IDLE_EXPECTED_IN_MODE: "이 모드에서는 입력이 없어도 정상",
    Reason.CAMERA_OFF: "카메라 사용 안 함",
    Reason.CAMERA_UNAVAILABLE: "카메라 사용 불가",
    Reason.FACE_STALE: "얼굴 관찰값이 오래됨",
    Reason.FACE_LOW_QUALITY: "얼굴 관찰 품질 낮음 (어두움·가림·멀리 있음)",
    Reason.FACE_FORWARD: "화면 방향 관찰",
    Reason.HEAD_DOWN: "아래쪽 방향 관찰 (단독으로 이탈 판정하지 않음)",
    Reason.HEAD_DOWN_READING: "아래쪽 방향 관찰 (독서·필기 모드)",
    Reason.HEAD_TURNED_AWAY: "화면 외 방향 관찰",
    Reason.FACE_NOT_VISIBLE: "카메라에 얼굴이 보이지 않음",
    Reason.INSUFFICIENT_EVIDENCE: "판단할 근거가 부족함",
    Reason.HYSTERESIS_HOLD: "짧은 변화라 이전 상태 유지",
}


def describe(codes: tuple[str, ...] | list[str]) -> list[str]:
    return [REASON_TEXT.get(code, code) for code in codes]  # type: ignore[call-overload]

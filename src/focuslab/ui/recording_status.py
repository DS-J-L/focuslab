"""Recorder health in plain words, shared by the home page, the activity page and the tray.

Observing (the recorder reads the foreground program) and saving (what it read reaches the
database) are reported separately: a recorder can observe fine while every save fails, and
that must never look like "recording"."""

from dataclasses import dataclass
from datetime import datetime

from focuslab.activity.recorder import RecorderState, RecorderStatus, wall_ms

WARNING_STYLE = "color:#C92A2A; font-weight:700;"  # a failing save, until a save works


@dataclass(frozen=True)
class RecordingHealth:
    text: str  # one line for a page header or the tray tooltip
    saving_failed: bool = False
    detail: str = ""  # the error itself, for a tooltip or a warning banner


def _clock(ms: int, now_ms: int) -> str:
    at, now = datetime.fromtimestamp(ms / 1000), datetime.fromtimestamp(now_ms / 1000)
    return f"{at:%H:%M:%S}" if at.date() == now.date() else f"{at:%m/%d %H:%M}"


def describe(
    status: RecorderStatus | None, consent: bool, now_ms: int | None = None
) -> RecordingHealth:
    now_ms = wall_ms() if now_ms is None else now_ms
    if not consent:
        return RecordingHealth("자동 기록 꺼짐 · 설정에서 켤 수 있습니다")
    if status is None or status.state is RecorderState.STOPPED:
        return RecordingHealth("자동 기록 중지됨")
    if status.state is RecorderState.PAUSED:
        observing = "자동 기록 일시정지됨"
    elif status.probe_error:
        observing = "● 관찰 불가 (프로그램을 읽지 못함)"
    else:
        observing = "● 관찰 중"
    last = _clock(status.last_save_ms, now_ms) if status.last_save_ms else "없음"
    if status.save_error:
        since = _clock(status.save_failing_since_ms or now_ms, now_ms)
        return RecordingHealth(
            f"{observing} · ⚠ 저장 실패 ({since}부터, 마지막 저장 {last})",
            saving_failed=True, detail=status.save_error,
        )
    saving = f"저장 정상 · 마지막 저장 {last}" if status.last_save_ms else "저장 대기 중"
    return RecordingHealth(f"{observing} · {saving}", detail=status.probe_error or "")

from datetime import datetime

from focuslab.activity.recorder import RecorderState, RecorderStatus
from focuslab.ui.recording_status import describe

NOW = int(datetime(2026, 10, 20, 15, 0, 0).timestamp() * 1000)
SAVED = NOW - 90_000  # 14:58:30
FAILING_SINCE = NOW - 60_000  # 14:59:00


def running(**kw) -> RecorderStatus:
    return RecorderStatus(RecorderState.RUNNING, last_save_ms=SAVED, **kw)


def test_without_consent_or_recorder():
    assert describe(running(), consent=False, now_ms=NOW).text.startswith("자동 기록 꺼짐")
    assert describe(None, consent=True, now_ms=NOW).text == "자동 기록 중지됨"
    stopped = RecorderStatus(RecorderState.STOPPED)
    assert describe(stopped, consent=True, now_ms=NOW).text == "자동 기록 중지됨"


def test_observing_and_saving_are_reported_separately():
    ok = describe(running(), consent=True, now_ms=NOW)
    assert ok.text == "● 관찰 중 · 저장 정상 · 마지막 저장 14:58:30"
    assert not ok.saving_failed

    blind = describe(running(probe_error="access denied"), consent=True, now_ms=NOW)
    assert blind.text.startswith("● 관찰 불가") and "저장 정상" in blind.text
    assert not blind.saving_failed and blind.detail == "access denied"

    failing = describe(
        running(save_error="disk I/O error", save_failing_since_ms=FAILING_SINCE),
        consent=True, now_ms=NOW,
    )
    assert failing.saving_failed and failing.detail == "disk I/O error"
    assert failing.text == "● 관찰 중 · ⚠ 저장 실패 (14:59:00부터, 마지막 저장 14:58:30)"


def test_paused_and_never_saved():
    paused = RecorderStatus(RecorderState.PAUSED, last_save_ms=SAVED)
    text = describe(paused, True, NOW).text
    assert text == "자동 기록 일시정지됨 · 저장 정상 · 마지막 저장 14:58:30"
    fresh = RecorderStatus(RecorderState.RUNNING)
    assert describe(fresh, True, NOW).text == "● 관찰 중 · 저장 대기 중"
    never = RecorderStatus(RecorderState.RUNNING, save_error="x", save_failing_since_ms=NOW)
    assert "마지막 저장 없음" in describe(never, True, NOW).text


def test_a_save_from_another_day_shows_the_date():
    old = RecorderStatus(RecorderState.RUNNING, last_save_ms=NOW - 86_400_000)
    assert "마지막 저장 10/19 15:00" in describe(old, True, NOW).text

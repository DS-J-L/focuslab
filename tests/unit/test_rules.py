"""Synthetic scenarios for the mode-aware rule engine (PR-06: at least 25 cases)."""

from dataclasses import replace

import pytest

from focuslab.domain.models import FocusState, SessionMode
from focuslab.focus.fusion import AppRelation, FaceEvidence, FusedFrame
from focuslab.focus.reasons import Reason
from focuslab.focus.rules import RuleEngine

ON, OFF, AWAY, BREAK, UNKNOWN = (
    FocusState.ON_TASK,
    FocusState.POSSIBLY_OFF_TASK,
    FocusState.AWAY,
    FocusState.BREAK,
    FocusState.UNKNOWN,
)


def frame(
    app=AppRelation.ALLOWED,
    face=FaceEvidence.FORWARD,
    idle=0.0,
    name="code.exe",
    reasons=(),
    brk=False,
    locked=False,
    browser=False,
):
    return FusedFrame(
        now_ms=0, app=app, face=face, app_name=name, idle_s=idle, reasons=reasons,
        screen_locked=locked, user_break=brk, is_browser=browser,
    )


def run(engine, frames):
    return [engine.evaluate(f) for f in frames]


def idle_seq(start, n, **kw):
    """n frames whose idle time grows by one second per frame."""
    return [frame(idle=start + i, **kw) for i in range(n)]


@pytest.fixture
def coding():
    return RuleEngine(SessionMode.CODING)


def settle_on_task(engine):
    assert engine.evaluate(frame()).state is ON


def test_allowed_app_and_forward_face_is_on_task(coding):
    d = coding.evaluate(frame())
    assert d.state is ON
    assert Reason.ALLOWED_APP in d.reason_codes and Reason.FACE_FORWARD in d.reason_codes


def test_session_start_on_unrelated_app_is_unknown_until_threshold(coding):
    out = run(coding, [frame(app=AppRelation.UNRELATED, name="game.exe")] * 15)
    assert all(d.state is UNKNOWN for d in out[:14])
    assert Reason.INSUFFICIENT_EVIDENCE in out[0].reason_codes
    assert out[14].state is OFF


def test_short_unrelated_app_keeps_previous_state(coding):
    settle_on_task(coding)
    out = run(coding, [frame(app=AppRelation.UNRELATED, name="kakaotalk.exe")] * 10)
    assert all(d.state is ON for d in out)
    assert Reason.UNRELATED_APP in out[-1].reason_codes
    assert Reason.HYSTERESIS_HOLD in out[-1].reason_codes


def test_unrelated_app_for_15_seconds_is_possibly_off_task(coding):
    settle_on_task(coding)
    out = run(coding, [frame(app=AppRelation.UNRELATED)] * 15)
    assert out[13].state is ON
    assert out[14].state is OFF
    assert out[14].reason_codes[0] == Reason.UNRELATED_APP


def test_return_to_task_needs_dwell(coding):
    settle_on_task(coding)
    run(coding, [frame(app=AppRelation.UNRELATED)] * 15)
    out = run(coding, [frame()] * 3)
    assert [d.state for d in out] == [OFF, OFF, ON]


def test_head_down_never_triggers_off_task_in_coding(coding):
    settle_on_task(coding)
    out = run(coding, idle_seq(0, 120, face=FaceEvidence.DOWN))
    assert all(d.state is ON for d in out)
    assert Reason.HEAD_DOWN in out[-1].reason_codes


def test_head_down_is_reading_evidence_in_reading_mode():
    engine = RuleEngine(SessionMode.READING_WRITING)
    d = engine.evaluate(frame(face=FaceEvidence.DOWN, idle=300))
    assert d.state is ON
    assert Reason.HEAD_DOWN_READING in d.reason_codes


def test_short_head_turn_keeps_on_task(coding):
    settle_on_task(coding)
    out = run(coding, idle_seq(0, 10, face=FaceEvidence.AWAY))
    assert all(d.state is ON for d in out)


def test_sustained_head_turn_with_idle_is_possibly_off_task(coding):
    settle_on_task(coding)
    out = run(coding, idle_seq(0, 15, face=FaceEvidence.AWAY))
    assert out[-1].state is OFF
    assert Reason.HEAD_TURNED_AWAY in out[-1].reason_codes


def test_head_turn_while_typing_is_not_off_task(coding):
    settle_on_task(coding)
    out = run(coding, [frame(face=FaceEvidence.AWAY, idle=1)] * 40)
    assert all(d.state is ON for d in out)


def test_face_absent_and_idle_becomes_away(coding):
    settle_on_task(coding)
    out = run(coding, idle_seq(5, 20, face=FaceEvidence.ABSENT))
    assert out[18].state is ON
    assert out[19].state is AWAY
    assert set(out[19].reason_codes) == {Reason.FACE_NOT_VISIBLE, Reason.USER_IDLE}


def test_face_absent_while_typing_is_on_task(coding):
    settle_on_task(coding)
    out = run(coding, [frame(face=FaceEvidence.ABSENT, idle=2)] * 30)
    assert all(d.state is ON for d in out)
    assert Reason.FACE_NOT_VISIBLE in out[-1].reason_codes


def test_reading_mode_waits_longer_before_away():
    engine = RuleEngine(SessionMode.READING_WRITING)
    engine.evaluate(frame(face=FaceEvidence.DOWN))
    out = run(engine, idle_seq(0, 60, face=FaceEvidence.ABSENT))
    assert all(d.state is ON for d in out[:59])
    assert out[59].state is AWAY


def test_camera_off_with_activity_is_on_task(coding):
    d = coding.evaluate(frame(face=FaceEvidence.OFF, idle=1, reasons=(Reason.CAMERA_OFF,)))
    assert d.state is ON
    assert Reason.CAMERA_OFF in d.reason_codes and Reason.USER_ACTIVE in d.reason_codes


def test_camera_off_long_idle_in_coding_becomes_unknown_not_off_task(coding):
    kw = {"face": FaceEvidence.OFF, "reasons": (Reason.CAMERA_OFF,)}
    coding.evaluate(frame(idle=0, **kw))
    out = run(coding, idle_seq(30, 100, **kw))
    assert all(d.state is ON for d in out[:90])  # idle 30..119 -> hold
    assert out[-1].state is UNKNOWN
    assert all(d.state is not OFF and d.state is not AWAY for d in out)


def test_camera_off_idle_is_normal_in_lecture():
    engine = RuleEngine(SessionMode.LECTURE)
    d = engine.evaluate(frame(face=FaceEvidence.OFF, idle=600, reasons=(Reason.CAMERA_OFF,)))
    assert d.state is ON
    assert Reason.IDLE_EXPECTED_IN_MODE in d.reason_codes


def test_camera_unavailable_never_means_away(coding):
    kw = {"face": FaceEvidence.UNKNOWN, "reasons": (Reason.CAMERA_UNAVAILABLE,)}
    out = run(coding, idle_seq(0, 200, **kw))
    assert all(d.state in (ON, UNKNOWN) for d in out)
    assert out[0].state is ON and Reason.CAMERA_UNAVAILABLE in out[0].reason_codes


def test_low_quality_face_does_not_count_as_absent(coding):
    settle_on_task(coding)
    kw = {"face": FaceEvidence.UNKNOWN, "reasons": (Reason.FACE_LOW_QUALITY,)}
    out = run(coding, idle_seq(0, 100, **kw))
    assert not any(d.state is AWAY for d in out)


def test_activity_unavailable_is_unknown(coding):
    d = coding.evaluate(
        frame(app=AppRelation.UNKNOWN, name=None, idle=None, reasons=(Reason.ACTIVITY_UNAVAILABLE,))
    )
    assert d.state is UNKNOWN
    assert Reason.ACTIVITY_UNAVAILABLE in d.reason_codes


def test_activity_unavailable_and_face_absent_is_low_confidence_away(coding):
    kw = {
        "app": AppRelation.UNKNOWN, "name": None, "idle": None, "face": FaceEvidence.ABSENT,
        "reasons": (Reason.ACTIVITY_UNAVAILABLE,),
    }
    out = run(coding, [frame(**kw)] * 20)
    assert out[-1].state is AWAY
    assert out[-1].confidence == pytest.approx(0.5)


def test_break_is_immediate_and_ends_immediately(coding):
    settle_on_task(coding)
    assert coding.evaluate(frame(brk=True)).state is BREAK
    assert coding.evaluate(frame()).state is ON


def test_break_resets_deviation_timers(coding):
    settle_on_task(coding)
    run(coding, [frame(app=AppRelation.UNRELATED)] * 10)
    coding.evaluate(frame(brk=True))
    out = run(coding, [frame(app=AppRelation.UNRELATED)] * 10)
    # Timers restart after the break, and BREAK is not carried over once it ends.
    assert all(d.state is UNKNOWN for d in out)


def test_screen_lock_becomes_unknown_after_dwell(coding):
    settle_on_task(coding)
    out = run(coding, [frame(locked=True, name=None)] * 3)
    assert [d.state for d in out] == [ON, ON, UNKNOWN]
    assert Reason.SCREEN_LOCKED in out[-1].reason_codes


def test_neutral_app_keeps_previous_state(coding):
    settle_on_task(coding)
    out = run(coding, [frame(app=AppRelation.NEUTRAL, name="explorer.exe", idle=50)] * 60)
    assert all(d.state is ON for d in out)
    assert Reason.NEUTRAL_APP in out[-1].reason_codes


def test_browser_is_flagged_as_detail_unknown(coding):
    d = coding.evaluate(frame(name="chrome.exe", browser=True))
    assert Reason.BROWSER_DETAIL_UNKNOWN in d.reason_codes


def test_single_tick_dropout_does_not_flicker(coding):
    settle_on_task(coding)
    dropout = frame(app=AppRelation.UNKNOWN, idle=None, reasons=(Reason.ACTIVITY_STALE,))
    out = run(coding, [dropout, frame(), dropout, dropout, frame()])
    assert all(d.state is ON for d in out)


def test_alt_tab_resets_unrelated_timer(coding):
    settle_on_task(coding)
    other = frame(app=AppRelation.UNRELATED)
    seq = [other] * 10 + [frame()] + [other] * 10
    assert all(d.state is ON for d in run(coding, seq))


def test_reset_forgets_state(coding):
    settle_on_task(coding)
    run(coding, [frame(app=AppRelation.UNRELATED)] * 15)
    coding.reset()
    assert coding.current is None
    assert coding.evaluate(frame()).state is ON


def test_same_inputs_give_same_outputs():
    seq = (
        idle_seq(0, 20, face=FaceEvidence.ABSENT)
        + [frame(app=AppRelation.UNRELATED)] * 20
        + [frame()] * 5
    )
    a = run(RuleEngine(SessionMode.CODING), seq)
    b = run(RuleEngine(SessionMode.CODING), seq)
    assert a == b


def test_off_task_on_unrelated_app_even_when_facing_screen(coding):
    settle_on_task(coding)
    out = run(coding, [frame(app=AppRelation.UNRELATED, face=FaceEvidence.FORWARD)] * 15)
    assert out[-1].state is OFF
    assert Reason.FACE_FORWARD in out[-1].reason_codes


def test_confidence_is_lower_without_camera(coding):
    with_camera = RuleEngine(SessionMode.CODING).evaluate(frame(idle=1))
    without = coding.evaluate(frame(face=FaceEvidence.OFF, idle=1, reasons=(Reason.CAMERA_OFF,)))
    assert without.confidence < with_camera.confidence


def test_possibly_related_app_is_unknown_and_never_off_task(coding):
    settle_on_task(coding)
    notes = replace(
        frame(app=AppRelation.POSSIBLY_RELATED, name="notepad.exe"),
        support=Reason.NOTE_TAKING_POSSIBLE,
    )
    out = run(coding, [notes] * 300)
    assert out[1].state is ON  # a brief switch keeps the previous state
    assert all(d.state is not OFF for d in out)
    assert out[-1].state is UNKNOWN
    assert Reason.NOTE_TAKING_POSSIBLE in out[-1].reason_codes


def test_facing_the_camera_does_not_confirm_a_possibly_related_app(coding):
    out = run(coding, [frame(app=AppRelation.POSSIBLY_RELATED, face=FaceEvidence.FORWARD)] * 30)
    assert all(d.state is UNKNOWN for d in out)


def test_allowed_browser_without_site_is_unknown_not_on_task(coding):
    out = run(coding, [frame(name="chrome.exe", browser=True)] * 30)
    assert all(d.state is UNKNOWN for d in out)
    assert Reason.BROWSER_DETAIL_UNKNOWN in out[-1].reason_codes


def test_allowed_browser_with_known_site_is_on_task(coding):
    known = replace(frame(name="chrome.exe", browser=True), domain="github.com")
    assert coding.evaluate(known).state is ON

"""Task relevance in the focus engine: evidence acts, uncertainty changes nothing."""

from dataclasses import replace

import pytest

from focuslab.config import RuleConfig
from focuslab.domain.models import ActivityObservation, FocusState, SessionMode
from focuslab.focus.fusion import AppRelation, FaceEvidence, FusedFrame, fuse
from focuslab.focus.reasons import Reason
from focuslab.focus.rules import RuleEngine
from focuslab.relevance.models import RelevanceLevel, TaskRelevanceResult

RELATED = TaskRelevanceResult(RelevanceLevel.RELATED, 1.0, ("TITLE_MATCHES_GOAL",), "RULE")
UNRELATED = TaskRelevanceResult(
    RelevanceLevel.POSSIBLY_UNRELATED, 0.0, ("TITLE_ENTERTAINMENT",), "RULE"
)
UNCERTAIN = TaskRelevanceResult(RelevanceLevel.UNCERTAIN, None, ("NO_EVIDENCE",), "RULE")
LIMIT = RuleConfig().unrelated_page_s


def obs(name="chrome.exe", allowed=True, idle=1.0, ts=0):
    return ActivityObservation(ts, name, allowed, idle, True, domain="youtube.com", page_title="t")


# fusion ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "allowed,name,expected",
    [
        (False, "chrome.exe", AppRelation.GOAL_RELATED),  # browser not on the allow list
        (False, "notepad.exe", AppRelation.GOAL_RELATED),  # would be POSSIBLY_RELATED
        (True, "chrome.exe", AppRelation.ALLOWED),
        (None, "explorer.exe", AppRelation.NEUTRAL),
    ],
)
def test_related_evidence_upgrades_only_apps_outside_the_allow_list(allowed, name, expected):
    frame = fuse(0, None, obs(name, allowed), camera_enabled=False, relevance=RELATED)
    assert frame.app is expected and frame.relevance is RELATED


def test_uncertain_or_unrelated_relevance_never_upgrades():
    for relevance in (UNCERTAIN, UNRELATED, None):
        frame = fuse(0, None, obs(allowed=False), camera_enabled=False, relevance=relevance)
        assert frame.app is AppRelation.UNRELATED


def test_relevance_from_a_stale_observation_is_dropped():
    frame = fuse(60_000, None, obs(ts=0), camera_enabled=False, relevance=UNRELATED)
    assert frame.app is AppRelation.UNKNOWN and frame.relevance is None


# rules ----------------------------------------------------------------------------------


def frame(app=AppRelation.ALLOWED, face=FaceEvidence.FORWARD, idle=1.0, relevance=None):
    return FusedFrame(
        now_ms=0, app=app, face=face, app_name="chrome.exe", idle_s=idle, is_browser=True,
        domain="youtube.com", relevance=relevance,
    )


def run(engine, f, seconds):
    return [engine.evaluate(f) for _ in range(seconds)][-1]


def test_an_unrelated_page_counts_only_after_it_lasts():
    engine = RuleEngine(SessionMode.LECTURE)
    assert run(engine, frame(), 5).state is FocusState.ON_TASK
    held = run(engine, frame(relevance=UNRELATED), int(LIMIT) - 1)
    assert held.state is FocusState.ON_TASK and Reason.HYSTERESIS_HOLD in held.reason_codes
    off = run(engine, frame(relevance=UNRELATED), 1)
    assert off.state is FocusState.POSSIBLY_OFF_TASK
    assert off.reason_codes[0] == Reason.PAGE_UNRELATED_TO_GOAL


def test_an_unrelated_page_with_nobody_evidently_there_is_unknown():
    engine = RuleEngine(SessionMode.LECTURE)
    f = frame(face=FaceEvidence.OFF, idle=300.0, relevance=UNRELATED)
    assert run(engine, f, int(LIMIT) + 5).state is FocusState.UNKNOWN


def test_absence_outranks_an_unrelated_page():
    engine = RuleEngine(SessionMode.LECTURE)
    f = frame(face=FaceEvidence.ABSENT, idle=300.0, relevance=UNRELATED)
    assert run(engine, f, int(LIMIT) + 30).state is FocusState.AWAY


def test_a_related_tool_outside_the_allow_list_counts_as_work():
    engine = RuleEngine(SessionMode.LECTURE)
    possible = run(engine, frame(app=AppRelation.POSSIBLY_RELATED), 10)
    assert possible.state is FocusState.UNKNOWN  # before: needs the user's confirmation
    related = run(engine, frame(app=AppRelation.GOAL_RELATED, relevance=RELATED), 10)
    assert related.state is FocusState.ON_TASK
    assert Reason.PAGE_RELATED_TO_GOAL in related.reason_codes
    assert Reason.ALLOWED_APP not in related.reason_codes


@pytest.mark.parametrize(
    "app,face,idle",
    [
        (AppRelation.ALLOWED, FaceEvidence.FORWARD, 1.0),
        (AppRelation.ALLOWED, FaceEvidence.OFF, 200.0),
        (AppRelation.UNRELATED, FaceEvidence.FORWARD, 1.0),
        (AppRelation.POSSIBLY_RELATED, FaceEvidence.DOWN, 1.0),
        (AppRelation.ALLOWED, FaceEvidence.ABSENT, 50.0),
    ],
)
def test_uncertain_relevance_changes_no_decision(app, face, idle):
    plain, judged = RuleEngine(SessionMode.CODING), RuleEngine(SessionMode.CODING)
    for _ in range(90):
        a = plain.evaluate(frame(app, face, idle))
        b = judged.evaluate(frame(app, face, idle, UNCERTAIN))
        assert (a.state, a.confidence, a.reason_codes) == (b.state, b.confidence, b.reason_codes)


def test_rule_config_changes_are_respected():
    engine = RuleEngine(SessionMode.LECTURE, replace(RuleConfig(), unrelated_page_s=5))
    run(engine, frame(), 3)
    assert run(engine, frame(relevance=UNRELATED), 5).state is FocusState.POSSIBLY_OFF_TASK

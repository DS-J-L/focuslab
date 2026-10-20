"""Task relevance engine: inputs, rules and the levels it may and may not reach."""

import pytest

from focuslab.domain.models import ActivityObservation, SessionMode
from focuslab.relevance.engine import RelevanceEngine
from focuslab.relevance.models import RelevanceInput, RelevanceLevel, RelevanceReason

GOAL = "증강현실 프로그래밍 공부"


def obs(name="chrome.exe", domain=None, title=None, idle=1.0, locked=False, available=True):
    return ActivityObservation(
        0, name, True, idle, available, screen_locked=locked, domain=domain, page_title=title
    )


def judge(goal=GOAL, mode=SessionMode.LECTURE, **kw):
    return RelevanceEngine().evaluate(RelevanceInput.of(goal, mode, obs(**kw)))


def test_input_carries_the_goal_and_the_title_of_the_same_observation():
    data = RelevanceInput.of(
        GOAL, SessionMode.LECTURE,
        obs(domain="youtube.com", title="Unity AR Foundation Tutorial"),
    )
    assert (data.goal, data.domain, data.page_title) == (
        GOAL, "youtube.com", "Unity AR Foundation Tutorial"
    )


def test_a_title_without_its_site_is_not_used():
    data = RelevanceInput.of(GOAL, SessionMode.LECTURE, obs(title="Some title"))
    assert data.page_title is None


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"available": False}, RelevanceReason.NO_ACTIVITY),
        ({"name": None}, RelevanceReason.NO_ACTIVITY),
        ({"locked": True}, RelevanceReason.INACTIVE),
        ({"idle": 600.0}, RelevanceReason.INACTIVE),
        ({"domain": "youtube.com"}, RelevanceReason.TITLE_UNAVAILABLE),
        ({}, RelevanceReason.TITLE_UNAVAILABLE),  # a browser without any report
    ],
)
def test_missing_input_is_uncertain_never_unrelated(kw, reason):
    result = judge(**kw)
    assert result.level is RelevanceLevel.UNCERTAIN
    assert result.reasons == (reason,)
    assert result.score is None


def test_no_goal_is_uncertain():
    result = judge(goal="  ", domain="youtube.com", title="게임 플레이 모음")
    assert result.level is RelevanceLevel.UNCERTAIN
    assert result.reasons == (RelevanceReason.NO_GOAL,)

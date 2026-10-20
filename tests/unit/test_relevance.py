"""Task relevance engine: inputs, rules and the levels it may and may not reach."""

import pytest

from focuslab.activity.classifier import classify
from focuslab.domain.activity import Category, SpanKind
from focuslab.domain.models import ActivityObservation, SessionMode
from focuslab.relevance.engine import RelevanceEngine
from focuslab.relevance.models import RelevanceInput, RelevanceLevel, RelevanceReason
from focuslab.relevance.rules import clean_title, goal_terms, match_title

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


# Rule engine --------------------------------------------------------------------------

RELATED, UNCERTAIN, UNRELATED = (
    RelevanceLevel.RELATED, RelevanceLevel.UNCERTAIN, RelevanceLevel.POSSIBLY_UNRELATED,
)


def rule(goal, name, domain=None, title=None, mode=SessionMode.LECTURE):
    return RelevanceEngine().evaluate(RelevanceInput(goal, mode, name, domain, title))


@pytest.mark.parametrize(
    "goal,name,domain,title,level",
    [
        # The plan's synthetic evaluation set (section 7).
        ("증강현실 공부", "chrome.exe", "youtube.com", "Unity AR Foundation Tutorial", RELATED),
        ("데이터베이스 시험공부", "chrome.exe", "youtube.com", "SQL 정규화 완벽 정리", RELATED),
        ("데이터베이스 시험공부", "chrome.exe", "youtube.com", "SQL JOIN 실습", RELATED),
        ("증강현실 공부", "chrome.exe", "youtube.com", "게임 플레이 모음", UNRELATED),
        ("증강현실 공부", "notepad.exe", None, None, UNCERTAIN),
        ("논문 작성", "chrome.exe", "chatgpt.com", "ChatGPT", UNCERTAIN),
        ("논문 작성", "claude.exe", None, None, UNCERTAIN),
        ("프로그래밍", "chrome.exe", "github.com", "Issues · DS-J-L/focuslab", UNCERTAIN),
        ("증강현실 공부", "chrome.exe", "youtube.com", "YouTube", UNCERTAIN),
        # More
        ("증강현실 공부", "chrome.exe", "youtube.com", "(3) Unity AR 기초 - YouTube", RELATED),
        ("운영체제 공부", "msedge.exe", "youtube.com", "프로세스와 스레드의 차이", RELATED),
        ("영어 공부", "chrome.exe", "youtube.com", "[MV] 좋은 날 뮤직비디오", UNRELATED),
        ("파이썬 공부", "chrome.exe", "youtube.com", "Syntax highlighting in VS Code", UNCERTAIN),
        ("증강현실 공부", "chrome.exe", "netflix.com", "Netflix", UNRELATED),
        ("증강현실 공부", "steam.exe", None, None, UNRELATED),
        ("증강현실 공부", "kakaotalk.exe", None, None, UNCERTAIN),
        ("증강현실 공부", "chrome.exe", "inflearn.com", None, UNCERTAIN),
        ("증강현실 공부", "code.exe", None, None, UNCERTAIN),
        # Media is part of these goals, so leisure-looking titles are not deviations.
        ("게임 기획 공부", "chrome.exe", "youtube.com", "게임 플레이 모음", UNCERTAIN),
        ("영화 리뷰 작성", "chrome.exe", "netflix.com", "Netflix", UNCERTAIN),
    ],
)
def test_rule_engine_scenarios(goal, name, domain, title, level):
    assert rule(goal, name, domain, title).level is level


def test_youtube_is_judged_by_title_not_as_entertainment():
    assert classify(SpanKind.ACTIVE, "chrome.exe", "youtube.com").category is Category.UNKNOWN
    lecture = rule("증강현실 공부", "chrome.exe", "youtube.com", "Unity AR Foundation Tutorial")
    vague = rule("증강현실 공부", "chrome.exe", "youtube.com", "오늘의 영상")
    assert lecture.level is RELATED and vague.level is UNCERTAIN


@pytest.mark.parametrize("name", ["notepad.exe", "claude.exe", "chatgpt.exe", "obsidian.exe"])
def test_support_tools_are_never_unrelated_by_name(name):
    result = rule("증강현실 공부", name)
    assert result.level is UNCERTAIN
    assert result.reasons == (RelevanceReason.SUPPORT_TOOL,)


def test_results_carry_reasons_source_and_a_bounded_score():
    result = rule("증강현실 프로그래밍 공부", "chrome.exe", "youtube.com", "Unity AR 기초 강의")
    assert result.level is RELATED
    assert result.reasons == (RelevanceReason.TITLE_MATCHES_GOAL,)
    assert result.source == "RULE"
    assert 0 < result.score <= 1


def test_goal_terms_drop_generic_words_and_particles():
    assert goal_terms("데이터베이스 시험공부") == ("데이터베이스",)
    assert goal_terms("증강현실을 공부하기") == ("증강현실",)
    assert goal_terms("Learn Rust ownership") == ("rust", "ownership")


def test_clean_title_drops_counts_and_the_site_name():
    assert clean_title("(12) SQL JOIN 실습 - YouTube", "youtube.com") == "SQL JOIN 실습"
    assert clean_title("A - B - YouTube", "www.youtube.com") == "A - B"
    assert clean_title("Rust - Wikipedia", "github.com") == "Rust - Wikipedia"


def test_latin_terms_match_whole_words_only():
    assert not match_title("AR 공부", "Learn Array methods").matched
    assert match_title("AR 공부", "AR Foundation basics").matched
    assert not match_title("파이썬 공부", "highlights of the match").matched

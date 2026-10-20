"""The user's relevance answers outrank automatic judgment and update recorded statistics."""

import pytest

from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.focus.metrics import apply_corrections, compute_metrics
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.relevance.engine import RelevanceEngine
from focuslab.relevance.explain import sentence, subject
from focuslab.relevance.feedback import FeedbackRules, RelevanceRules, TargetKind
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    TaskRelevanceResult,
)
from focuslab.services.session_service import SessionService
from focuslab.storage.sqlite_db import connect

GAME = ("chrome.exe", "youtube.com", "게임 플레이 모음 - YouTube")
LECTURE = ("chrome.exe", "youtube.com", "Unity AR Foundation 기초 강의")


def data(goal, activity):
    return RelevanceInput(goal, SessionMode.LECTURE, *activity)


# rules store and lookup -----------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "r.db")
    yield RelevanceRules(conn)
    conn.close()


def test_rules_are_kept_per_target_and_replaced_by_a_newer_answer(store):
    goal = "증강현실 공부"
    assert store.add(goal, data(goal, GAME), RelevanceLevel.RELATED)
    assert store.add(goal, data(goal, GAME), RelevanceLevel.POSSIBLY_UNRELATED)
    assert store.add(goal, data(goal, ("notepad.exe", None, None)), RelevanceLevel.RELATED)
    rules = store.all()
    assert [(r.kind, r.level) for r in rules] == [
        (TargetKind.APP, RelevanceLevel.RELATED),
        (TargetKind.PAGE, RelevanceLevel.POSSIBLY_UNRELATED),
    ]
    assert rules[1].label == "youtube.com · 게임 플레이 모음"  # the site name is trimmed
    assert rules[1].goal_terms == ("증강현실",)
    store.clear_pages()
    assert [r.kind for r in store.all()] == [TargetKind.APP]
    store.delete(store.all()[0].id)
    assert store.all() == []


def test_rules_apply_to_similar_goals_only(store):
    store.add("증강현실 공부", data("증강현실 공부", GAME), RelevanceLevel.RELATED)
    similar = FeedbackRules("증강현실 프로그래밍 기초", store.all())
    other = FeedbackRules("토익 영어 공부", store.all())
    result = similar.lookup(data("증강현실 프로그래밍 기초", GAME))
    assert result.level is RelevanceLevel.RELATED and result.source == "USER"
    assert result.reasons == (RelevanceReason.USER_SAYS_HELPFUL, RelevanceReason.USER_RULE)
    assert other.lookup(data("토익 영어 공부", GAME)) is None


def test_a_site_rule_covers_its_pages(store):
    goal = "증강현실 공부"
    store.add(goal, data(goal, ("chrome.exe", "netflix.com", None)), RelevanceLevel.RELATED)
    rules = FeedbackRules(goal, store.all())
    assert rules.lookup(data(goal, ("chrome.exe", "netflix.com", "Any show"))) is not None


def test_a_one_time_answer_lasts_until_the_activity_changes():
    rules = FeedbackRules("증강현실 공부")
    rules.answer(data("증강현실 공부", GAME), RelevanceLevel.RELATED)
    assert rules.lookup(data("증강현실 공부", GAME)).level is RelevanceLevel.RELATED
    assert rules.lookup(data("증강현실 공부", LECTURE)) is None
    assert rules.lookup(data("증강현실 공부", GAME)) is None  # used up


def test_the_users_answer_outranks_rules_and_the_model():
    engine = RelevanceEngine()
    goal = "증강현실 공부"
    assert engine.evaluate(data(goal, GAME)).level is RelevanceLevel.POSSIBLY_UNRELATED
    engine.feedback.answer(data(goal, GAME), RelevanceLevel.RELATED)
    assert engine.evaluate(data(goal, GAME)).level is RelevanceLevel.RELATED
    engine.forget_titles()
    assert engine.evaluate(data(goal, GAME)).level is RelevanceLevel.POSSIBLY_UNRELATED


# session --------------------------------------------------------------------------------


@pytest.fixture
def make(tmp_path, clock):
    created = []

    def build(script):
        svc = SessionService(
            tmp_path / "s.db",
            face_factory=lambda cfg: MockFaceSource(((3600, "forward"),), clock),
            activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, script),
            clock=clock,
            auto_tick=False,
        )
        created.append(svc)
        return svc

    yield build
    for svc in created:
        svc.shutdown()


def tick(svc, clock, n):
    out = []
    for _ in range(n):
        clock.advance(1)
        out.append(svc.tick())
    return out


def config(goal="증강현실 공부"):
    return SessionConfig(goal, SessionMode.LECTURE, 0, ("chrome.exe",), True)


def effective(svc):
    sid = svc.snapshot().session_id
    repo = svc.repository
    return apply_corrections(repo.samples(sid), repo.segments(sid))


def test_not_related_corrects_only_the_seconds_of_this_page(make, clock):
    svc = make(((40, "chrome.exe", "active", *LECTURE[1:]), (3600, "chrome.exe", "active",
                                                              *GAME[1:])))
    svc.start(config())
    tick(svc, clock, 40 + 20)  # 40 s lecture, 20 s of the game held as ON_TASK
    assert svc.snapshot().decision.state is FocusState.ON_TASK
    assert svc.answer_relevance(RelevanceLevel.POSSIBLY_UNRELATED)
    states = [s.state for s in effective(svc)]
    assert FocusState.POSSIBLY_OFF_TASK not in states[:40]  # the lecture keeps its estimate
    assert set(states[40:]) == {FocusState.POSSIBLY_OFF_TASK}  # from its first second
    assert tick(svc, clock, 1)[-1].state is FocusState.POSSIBLY_OFF_TASK  # no 60 s wait
    snap = svc.snapshot()
    assert snap.relevance.source == "USER"
    metrics = compute_metrics(effective(svc))
    assert metrics.seconds[FocusState.POSSIBLY_OFF_TASK] >= 20
    assert metrics.goal_unrelated_s >= 1


def test_helps_the_task_turns_the_page_into_work(make, clock):
    svc = make(((3600, "chrome.exe", "active", *GAME[1:]),))
    svc.start(config())
    tick(svc, clock, 90)
    assert svc.snapshot().decision.state is FocusState.POSSIBLY_OFF_TASK
    svc.answer_relevance(RelevanceLevel.RELATED)
    assert {s.state for s in effective(svc)} == {FocusState.ON_TASK}
    tick(svc, clock, 5)
    assert svc.snapshot().decision.state is FocusState.ON_TASK


def test_not_sure_corrects_nothing_and_stops_automatic_flags(make, clock):
    svc = make(((3600, "chrome.exe", "active", *GAME[1:]),))
    svc.start(config())
    tick(svc, clock, 30)
    before = [s.state for s in effective(svc)]
    svc.answer_relevance(RelevanceLevel.UNCERTAIN)
    assert [s.state for s in effective(svc)] == before
    states = [d.state for d in tick(svc, clock, 90)]
    assert FocusState.POSSIBLY_OFF_TASK not in states


def test_a_remembered_answer_is_used_in_a_later_session_with_a_similar_goal(make, clock):
    svc = make(((3600, "chrome.exe", "active", *GAME[1:]),))
    svc.start(config())
    tick(svc, clock, 5)
    svc.answer_relevance(RelevanceLevel.RELATED, remember=True)
    svc.finish()
    svc.start(config("증강현실 앱 만들기"))
    tick(svc, clock, 90)
    snap = svc.snapshot()
    assert snap.relevance.level is RelevanceLevel.RELATED
    assert RelevanceReason.USER_RULE in snap.relevance.reasons
    assert snap.decision.state is FocusState.ON_TASK


def test_answers_need_a_session_and_an_activity(make, clock):
    svc = make(((3600, "chrome.exe", "active", *GAME[1:]),))
    assert not svc.answer_relevance(RelevanceLevel.RELATED)
    svc.start(config())
    assert not svc.answer_relevance(RelevanceLevel.RELATED)  # nothing observed yet


def test_withdrawing_title_consent_drops_page_rules(make, clock):
    svc = make(((3600, "chrome.exe", "active", *GAME[1:]),))
    svc.start(config())
    tick(svc, clock, 2)
    svc.answer_relevance(RelevanceLevel.RELATED, remember=True)
    svc.forget_page_titles()
    assert RelevanceRules(svc.repository.conn).all() == []


# sentences ------------------------------------------------------------------------------


def test_sentences_describe_what_was_seen_and_how_it_counts():
    goal, what = "증강현실 공부", subject(data("증강현실 공부", GAME))
    assert what == "게임 플레이 모음"
    related = TaskRelevanceResult(RelevanceLevel.RELATED, 1.0, (), "RULE")
    unrelated = TaskRelevanceResult(RelevanceLevel.POSSIBLY_UNRELATED, 0.0, (), "RULE")
    told = TaskRelevanceResult(RelevanceLevel.UNCERTAIN, None, (), "USER")
    assert "관련된 활동으로 보입니다" in sentence(related, goal, what)
    assert "작업 이탈로 기록될 수 있습니다" in sentence(unrelated, goal, what)
    assert "모르겠다고" in sentence(told, goal, what)
    assert sentence(None, goal, None) == "아직 목표와 비교할 활동이 없습니다."

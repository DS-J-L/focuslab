"""Activity context: order and duration change relevance, without inferring too much."""

from focuslab.domain.models import SessionMode
from focuslab.relevance.context import ActivityContext, ContextConfig
from focuslab.relevance.engine import RelevanceEngine
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    TaskRelevanceResult,
)

GOAL = "증강현실 공부"
LECTURE = ("chrome.exe", "youtube.com", "Unity AR Foundation 기초 강의")  # rules: RELATED
GAME = ("chrome.exe", "youtube.com", "게임 플레이 모음")  # rules: POSSIBLY_UNRELATED
NOTES = ("notepad.exe", None, None)  # rules: UNCERTAIN (support tool)
AI = ("chrome.exe", "chatgpt.com", "ChatGPT")  # rules: UNCERTAIN (support tool)
SHELL = ("explorer.exe", None, None)  # rules: UNCERTAIN (neutral, never support)
VAGUE = ("chrome.exe", "youtube.com", "오늘의 영상")  # rules: UNCERTAIN (no evidence)


class Timeline:
    """Feeds one tick per second, like the session service."""

    def __init__(self, engine=None):
        self.engine = engine or RelevanceEngine()
        self.now = 1_000_000

    def run(self, activity, seconds, idle=0.0, locked=False, step=1):
        result = None
        for _ in range(int(seconds)):
            self.now += 1000 * step
            name, domain, title = activity
            data = RelevanceInput(
                GOAL, SessionMode.LECTURE, name, domain, title, locked=locked, idle_s=idle
            )
            result = self.engine.evaluate(data, self.now)
        return result


def test_notes_right_after_a_lecture_support_it():
    t = Timeline()
    assert t.run(LECTURE, 60).level is RelevanceLevel.RELATED
    notes = t.run(NOTES, 30)
    assert notes.level is RelevanceLevel.RELATED and notes.source == "CONTEXT"
    assert notes.reasons[0] == RelevanceReason.FOLLOWS_RELATED_WORK
    assert RelevanceReason.SUPPORT_TOOL in notes.reasons  # the rule evidence stays visible


def test_the_same_app_after_a_game_stays_uncertain():
    t = Timeline()
    t.run(GAME, 60)
    assert t.run(NOTES, 30).level is RelevanceLevel.UNCERTAIN


def test_a_brief_glance_at_a_lecture_does_not_anchor_support():
    t = Timeline()
    t.run(SHELL, 30)
    t.run(LECTURE, 10)  # under min_related_s
    assert t.run(NOTES, 30).level is RelevanceLevel.UNCERTAIN


def test_a_blip_between_lecture_and_notes_is_ignored():
    t = Timeline()
    t.run(LECTURE, 60)
    t.run(SHELL, 2)  # alt-tab through the desktop
    assert t.run(NOTES, 10).level is RelevanceLevel.RELATED


def test_support_does_not_last_forever():
    t = Timeline(RelevanceEngine(context=ActivityContext(ContextConfig(support_max_s=120))))
    t.run(LECTURE, 60)
    assert t.run(NOTES, 100).level is RelevanceLevel.RELATED
    assert t.run(NOTES, 30).level is RelevanceLevel.UNCERTAIN


def test_back_and_forth_with_task_work_marks_the_tool_as_support():
    t = Timeline()
    t.run(LECTURE, 60)
    t.run(AI, 30)
    t.run(LECTURE, 60)
    t.run(SHELL, 20)  # not right after task work any more
    result = t.run(AI, 10)
    assert result.level is RelevanceLevel.RELATED
    assert result.reasons[0] == RelevanceReason.ALTERNATES_WITH_WORK


def test_the_desktop_is_never_counted_as_support():
    t = Timeline()
    t.run(LECTURE, 60)
    assert t.run(SHELL, 10).reasons == (RelevanceReason.NEUTRAL_APP,)


def test_context_results_never_anchor_further_support():
    t = Timeline()
    t.run(LECTURE, 60)
    t.run(NOTES, 60)  # RELATED only through context
    assert t.run(VAGUE, 30).level is RelevanceLevel.UNCERTAIN


def test_missing_ticks_and_a_locked_screen_break_the_chain():
    t = Timeline()
    t.run(LECTURE, 60)
    t.run(NOTES, 1, step=30)  # nothing observed for half a minute
    assert t.run(NOTES, 10).level is RelevanceLevel.UNCERTAIN

    t = Timeline()
    t.run(LECTURE, 60)
    assert t.run(LECTURE, 5, locked=True).reasons == (RelevanceReason.INACTIVE,)
    assert t.run(NOTES, 10).level is RelevanceLevel.UNCERTAIN


def test_being_away_from_an_app_breaks_the_chain_but_watching_a_page_does_not():
    t = Timeline()
    t.run(LECTURE, 300, idle=200.0)  # a lecture watched without touching anything
    assert t.run(NOTES, 10).level is RelevanceLevel.RELATED
    t.run(NOTES, 5, idle=200.0)  # nobody typing in the notes for minutes
    assert t.run(NOTES, 10).level is RelevanceLevel.UNCERTAIN


class StubSemantic:
    """Answers every title with a fixed margin, as the model would after warming up."""

    version = "stub"

    def __init__(self, margin):
        self.margin = margin

    def lookup(self, goal, title):
        return self.margin

    def forget_titles(self):
        pass


def test_a_leisure_like_page_is_a_deviation_only_after_it_stays():
    engine = RelevanceEngine(StubSemantic(-0.08))
    t = Timeline(engine)
    first = t.run(VAGUE, 60)
    assert first.level is RelevanceLevel.UNCERTAIN
    assert first.reasons == (RelevanceReason.TITLE_CLOSER_TO_LEISURE,)
    later = t.run(VAGUE, 150, idle=500.0)  # watched passively for minutes
    assert later.level is RelevanceLevel.POSSIBLY_UNRELATED
    assert later.reasons[0] == RelevanceReason.SUSTAINED_LEISURE_LIKE and later.source == "CONTEXT"


def test_rule_and_model_verdicts_are_never_overridden():
    ctx = ActivityContext()
    data = RelevanceInput(GOAL, SessionMode.LECTURE, *GAME)
    unrelated = TaskRelevanceResult(RelevanceLevel.POSSIBLY_UNRELATED, 0.0, ("X",), "RULE")
    ctx.update(RelevanceInput(GOAL, SessionMode.LECTURE, *LECTURE),
               TaskRelevanceResult(RelevanceLevel.RELATED, 1.0, ("Y",), "RULE"), 0)
    assert ctx.update(data, unrelated, 60_000) is unrelated

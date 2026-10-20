"""Task relevance contracts, kept apart from the activity category and the focus state.

- Activity category: what kind of program or site is in front (``activity.classifier``).
- Task relevance: whether that activity plausibly serves the session goal (this package).
- Focus state: whether work is observed to continue (``focus.rules``).

A related page title does not prove focus, and a vague one is not evidence of distraction.
``score`` is an internal rule weight or similarity, never a probability of being on task.
"""

from dataclasses import dataclass
from enum import StrEnum

from focuslab.domain.models import ActivityObservation, SessionMode
from focuslab.i18n import LocalizedMapping


class RelevanceLevel(StrEnum):
    RELATED = "RELATED"
    UNCERTAIN = "UNCERTAIN"
    POSSIBLY_UNRELATED = "POSSIBLY_UNRELATED"


class RelevanceSource(StrEnum):
    INPUT = "INPUT"  # not enough input to judge at all
    RULE = "RULE"
    EMBEDDING = "EMBEDDING"  # local language model similarity
    CONTEXT = "CONTEXT"  # order and duration of recent activities


class RelevanceReason(StrEnum):
    NO_GOAL = "NO_GOAL"
    NO_ACTIVITY = "NO_ACTIVITY"
    INACTIVE = "INACTIVE"
    TITLE_UNAVAILABLE = "TITLE_UNAVAILABLE"
    NO_EVIDENCE = "NO_EVIDENCE"
    TITLE_UNINFORMATIVE = "TITLE_UNINFORMATIVE"
    TITLE_MATCHES_GOAL = "TITLE_MATCHES_GOAL"
    TITLE_ENTERTAINMENT = "TITLE_ENTERTAINMENT"
    TITLE_MIXED_SIGNALS = "TITLE_MIXED_SIGNALS"
    ENTERTAINMENT_ACTIVITY = "ENTERTAINMENT_ACTIVITY"
    SUPPORT_TOOL = "SUPPORT_TOOL"
    COMMUNICATION = "COMMUNICATION"
    NEUTRAL_APP = "NEUTRAL_APP"
    TITLE_SIMILAR_TO_GOAL = "TITLE_SIMILAR_TO_GOAL"
    TITLE_CLOSER_TO_LEISURE = "TITLE_CLOSER_TO_LEISURE"
    FOLLOWS_RELATED_WORK = "FOLLOWS_RELATED_WORK"
    ALTERNATES_WITH_WORK = "ALTERNATES_WITH_WORK"
    SUSTAINED_LEISURE_LIKE = "SUSTAINED_LEISURE_LIKE"


RELEVANCE_REASON_TEXT = LocalizedMapping(
    {
        RelevanceReason.NO_GOAL: "No session goal to compare with",
        RelevanceReason.NO_ACTIVITY: "Current activity unavailable",
        RelevanceReason.INACTIVE: "Screen locked; relevance not judged",
        RelevanceReason.TITLE_UNAVAILABLE: (
            "Page title unavailable (not reported, stale, or not permitted)"
        ),
        RelevanceReason.NO_EVIDENCE: "No evidence linking this activity to the goal",
        RelevanceReason.TITLE_UNINFORMATIVE: "Page title too generic to judge",
        RelevanceReason.TITLE_MATCHES_GOAL: "Page title shares key terms with the goal",
        RelevanceReason.TITLE_ENTERTAINMENT: (
            "Page title suggests entertainment unrelated to the goal"
        ),
        RelevanceReason.TITLE_MIXED_SIGNALS: (
            "Page title mentions the goal but also looks like entertainment"
        ),
        RelevanceReason.ENTERTAINMENT_ACTIVITY: (
            "Game or entertainment program or site unrelated to the goal"
        ),
        RelevanceReason.SUPPORT_TOOL: (
            "Notes, AI assistant or work tool; may serve the task (judgment deferred)"
        ),
        RelevanceReason.COMMUNICATION: "Messenger or mail; may or may not concern the task",
        RelevanceReason.NEUTRAL_APP: "Desktop, app switcher or FocusLab; not judged",
        RelevanceReason.TITLE_SIMILAR_TO_GOAL: (
            "The local language model finds the page title close in meaning to the goal"
        ),
        RelevanceReason.TITLE_CLOSER_TO_LEISURE: (
            "The page title reads closer to leisure topics than to the goal (not conclusive)"
        ),
        RelevanceReason.FOLLOWS_RELATED_WORK: (
            "Opened right after task-related work; probably supporting it"
        ),
        RelevanceReason.ALTERNATES_WITH_WORK: (
            "Used back and forth with task-related work; probably supporting it"
        ),
        RelevanceReason.SUSTAINED_LEISURE_LIKE: (
            "A page that reads like leisure has stayed in front for several minutes"
        ),
    }
)


@dataclass(frozen=True)
class TaskRelevanceResult:
    level: RelevanceLevel
    score: float | None
    reasons: tuple[str, ...]
    source: str
    model_version: str | None = None


def uncertain(*reasons: str, source: str = RelevanceSource.INPUT) -> TaskRelevanceResult:
    return TaskRelevanceResult(RelevanceLevel.UNCERTAIN, None, reasons, source)


@dataclass(frozen=True)
class RelevanceInput:
    """The session goal and the foreground activity observed in the same tick."""

    goal: str
    mode: SessionMode
    process_name: str | None
    domain: str | None = None
    page_title: str | None = None
    available: bool = True
    locked: bool = False
    # Seconds without input. A page's relevance does not change while it is watched, so idle
    # time only matters to the activity context (and to presence, judged by the focus rules).
    idle_s: float | None = None

    @staticmethod
    def of(goal: str, mode: SessionMode, obs: ActivityObservation | None) -> "RelevanceInput":
        if obs is None or not obs.available:
            return RelevanceInput(goal, mode, None, available=False)
        return RelevanceInput(
            goal,
            mode,
            obs.process_name,
            obs.domain,
            obs.page_title if obs.domain else None,
            locked=obs.screen_locked,
            idle_s=obs.idle_seconds,
        )

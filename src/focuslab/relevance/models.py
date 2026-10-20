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


class RelevanceReason(StrEnum):
    NO_GOAL = "NO_GOAL"
    NO_ACTIVITY = "NO_ACTIVITY"
    INACTIVE = "INACTIVE"
    TITLE_UNAVAILABLE = "TITLE_UNAVAILABLE"
    NO_EVIDENCE = "NO_EVIDENCE"


RELEVANCE_REASON_TEXT = LocalizedMapping(
    {
        RelevanceReason.NO_GOAL: "No session goal to compare with",
        RelevanceReason.NO_ACTIVITY: "Current activity unavailable",
        RelevanceReason.INACTIVE: "Screen locked or no recent input; relevance not judged",
        RelevanceReason.TITLE_UNAVAILABLE: (
            "Page title unavailable (not reported, stale, or not permitted)"
        ),
        RelevanceReason.NO_EVIDENCE: "No evidence linking this activity to the goal",
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
    inactive: bool = False  # screen locked or idle past the session's active threshold

    @staticmethod
    def of(
        goal: str,
        mode: SessionMode,
        obs: ActivityObservation | None,
        active_idle_s: float = 30.0,
    ) -> "RelevanceInput":
        if obs is None or not obs.available:
            return RelevanceInput(goal, mode, None, available=False)
        idle = obs.idle_seconds
        return RelevanceInput(
            goal,
            mode,
            obs.process_name,
            obs.domain,
            obs.page_title if obs.domain else None,
            inactive=obs.screen_locked or (idle is not None and idle >= active_idle_s),
        )

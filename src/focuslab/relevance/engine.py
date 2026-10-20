"""Task relevance engine: one result per session tick, cheap enough to run under its lock.

Missing input (no goal, no activity, locked screen, idle, no permitted title) is UNCERTAIN,
never POSSIBLY_UNRELATED. Rules decide first; when they find no evidence about a page title,
the optional local model is consulted. Its answer arrives on a later tick (it never blocks
this one); until then, and whenever the model is off or missing, the rule result stands.
Finally the activity context may adjust the result from the order and duration of visits.
"""

from focuslab.relevance import rules
from focuslab.relevance.context import ActivityContext
from focuslab.relevance.embedding import LEISURE_AT, RELATED_AT, SemanticAnalyzer
from focuslab.relevance.feedback import FeedbackRules
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    RelevanceSource,
    TaskRelevanceResult,
    uncertain,
)

RELEVANCE_VERSION = "relevance-0.4"


def semantic_result(margin: float, model_version: str) -> TaskRelevanceResult:
    """A margin at or above RELATED_AT is related; a low one is only a hint, never a verdict."""
    if margin >= RELATED_AT:
        level, reason = RelevanceLevel.RELATED, RelevanceReason.TITLE_SIMILAR_TO_GOAL
    elif margin <= LEISURE_AT:
        level, reason = RelevanceLevel.UNCERTAIN, RelevanceReason.TITLE_CLOSER_TO_LEISURE
    else:
        level, reason = RelevanceLevel.UNCERTAIN, RelevanceReason.NO_EVIDENCE
    return TaskRelevanceResult(
        level, round(margin, 4), (reason,), RelevanceSource.EMBEDDING, model_version
    )


class RelevanceEngine:
    version = RELEVANCE_VERSION

    def __init__(
        self, semantic: SemanticAnalyzer | None = None, context: ActivityContext | None = None
    ) -> None:
        self.semantic = semantic
        self.context = context or ActivityContext()
        self.feedback = FeedbackRules()

    def evaluate(self, data: RelevanceInput, now_ms: int | None = None) -> TaskRelevanceResult:
        """Judge one tick; with ``now_ms`` the activity context takes part as well."""
        result = self._judge(data)
        if now_ms is None:
            return result
        return self.context.update(data, result, now_ms)

    def reset_context(self) -> None:
        """Forget visit history (new session, pause, observation gap)."""
        self.context.reset()

    def _judge(self, data: RelevanceInput) -> TaskRelevanceResult:
        if not data.goal.strip():
            return uncertain(RelevanceReason.NO_GOAL)
        if not data.available or not data.process_name:
            return uncertain(RelevanceReason.NO_ACTIVITY)
        if data.locked:
            return uncertain(RelevanceReason.INACTIVE)
        answer = self.feedback.lookup(data)
        if answer is not None:  # the user's answer outranks every automatic judgment
            return answer
        result = rules.judge(data)
        semantic = self.semantic
        if (
            semantic is not None
            and data.page_title
            and result.reasons == (RelevanceReason.NO_EVIDENCE,)
        ):
            title = rules.clean_title(data.page_title, data.domain)
            margin = semantic.lookup(data.goal.strip(), title)
            if margin is not None:
                return semantic_result(margin, semantic.version)
        return result

    def forget_titles(self) -> None:
        """Drop anything derived from page titles (consent withdrawn)."""
        self.context.reset()
        self.feedback.forget_titles()
        if self.semantic is not None:
            self.semantic.forget_titles()

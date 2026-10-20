"""Task relevance engine: one result per session tick, cheap enough to run under its lock.

Missing input (no goal, no activity, locked screen, idle, no permitted title) is UNCERTAIN,
never POSSIBLY_UNRELATED.
"""

from focuslab.activity.windows_tracker import normalize
from focuslab.config import BROWSERS
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceReason,
    TaskRelevanceResult,
    uncertain,
)

RELEVANCE_VERSION = "relevance-0.1"


class RelevanceEngine:
    version = RELEVANCE_VERSION

    def evaluate(self, data: RelevanceInput) -> TaskRelevanceResult:
        if not data.goal.strip():
            return uncertain(RelevanceReason.NO_GOAL)
        if not data.available or not data.process_name:
            return uncertain(RelevanceReason.NO_ACTIVITY)
        if data.inactive:
            return uncertain(RelevanceReason.INACTIVE)
        if not data.page_title and (data.domain or normalize(data.process_name) in BROWSERS):
            return uncertain(RelevanceReason.TITLE_UNAVAILABLE)
        return uncertain(RelevanceReason.NO_EVIDENCE)

    def forget_titles(self) -> None:
        """Drop anything derived from page titles (consent withdrawn)."""

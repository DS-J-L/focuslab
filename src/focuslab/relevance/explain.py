"""Plain sentences about a relevance result, for the session page.

A sentence states what was observed and how it counts; it never claims to know what the
user intended. UNCERTAIN says so and that it is not counted either way.
"""

from focuslab.i18n import LocalizedMapping, tr
from focuslab.relevance.models import (
    RELEVANCE_REASON_TEXT,
    RelevanceInput,
    RelevanceLevel,
    RelevanceSource,
    TaskRelevanceResult,
)
from focuslab.relevance.rules import clean_title

SOURCE_TEXT = LocalizedMapping(
    {
        RelevanceSource.INPUT: "Not enough input",
        RelevanceSource.RULE: "Rules",
        RelevanceSource.EMBEDDING: "Local language model",
        RelevanceSource.CONTEXT: "Order of recent activities",
        RelevanceSource.USER: "You",
    }
)

RELEVANCE_LEVEL_LABELS = LocalizedMapping(
    {
        RelevanceLevel.RELATED: "Helps the task",
        RelevanceLevel.POSSIBLY_UNRELATED: "Not related",
        RelevanceLevel.UNCERTAIN: "Not sure",
    }
)

_AUTOMATIC = {
    RelevanceLevel.RELATED: (
        "This looks related to the current task: '{p1}' is in front while you work on '{p0}'."
    ),
    RelevanceLevel.POSSIBLY_UNRELATED: (
        "This looks like a switch to something else: '{p1}' seems unrelated to '{p0}'. If it "
        "continues, this time may be recorded as possibly off task."
    ),
    RelevanceLevel.UNCERTAIN: (
        "Not sure whether '{p1}' relates to '{p0}', so it is not counted either way."
    ),
}
_ANSWERED = {
    RelevanceLevel.RELATED: "You said '{p1}' helps with '{p0}'.",
    RelevanceLevel.POSSIBLY_UNRELATED: "You said '{p1}' is not related to '{p0}'.",
    RelevanceLevel.UNCERTAIN: "You were not sure about '{p1}'; it is left undecided.",
}


def subject(data: RelevanceInput | None) -> str | None:
    """What is in front, in the user's words: the page title, else the site, else the app."""
    if data is None or not data.process_name:
        return None
    if data.page_title:
        return clean_title(data.page_title, data.domain)
    return data.domain or data.process_name


def sentence(result: TaskRelevanceResult | None, goal: str, what: str | None) -> str:
    if result is None or what is None:
        return tr("No activity to compare with the goal yet.")
    if result.source == RelevanceSource.INPUT:
        return " ".join(RELEVANCE_REASON_TEXT.get(r, r) for r in result.reasons)
    table = _ANSWERED if result.source == RelevanceSource.USER else _AUTOMATIC
    return tr(table[result.level], p0=goal, p1=what)


def evidence(result: TaskRelevanceResult | None) -> str:
    """Reasons and where the judgment came from, on one line."""
    if result is None:
        return ""
    reasons = " · ".join(RELEVANCE_REASON_TEXT.get(r, r) for r in result.reasons)
    return tr("{p0} ({p1})", p0=reasons, p1=SOURCE_TEXT.get(result.source, result.source))

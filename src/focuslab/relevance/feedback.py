"""The user's answers about task relevance, which outrank every automatic judgment.

An answer covers the current visit (until the foreground activity changes), or, if the user
asks, becomes a rule reused for similar goals: a goal sharing at least one key term with the
goal the rule was made for (``rules.goal_terms``). A rule names the most specific target that
was known: the page title, else the site, else the program.
"""

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from focuslab.relevance import rules
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    RelevanceSource,
    TaskRelevanceResult,
)
from focuslab.storage.repository import utc_now


class TargetKind(StrEnum):
    PAGE = "PAGE"
    SITE = "SITE"
    APP = "APP"


ANSWER_REASON = {
    RelevanceLevel.RELATED: RelevanceReason.USER_SAYS_HELPFUL,
    RelevanceLevel.POSSIBLY_UNRELATED: RelevanceReason.USER_SAYS_UNRELATED,
    RelevanceLevel.UNCERTAIN: RelevanceReason.USER_UNSURE,
}


def target(data: RelevanceInput) -> tuple[TargetKind, str] | None:
    if data.page_title:
        title = rules.clean_title(data.page_title, data.domain)
        return TargetKind.PAGE, f"{data.domain or ''}\n{title}"
    if data.domain:
        return TargetKind.SITE, data.domain
    if data.process_name:
        return TargetKind.APP, data.process_name.strip().lower()
    return None


def user_result(level: RelevanceLevel, rule: bool = False) -> TaskRelevanceResult:
    reasons = (ANSWER_REASON[level], *((RelevanceReason.USER_RULE,) if rule else ()))
    return TaskRelevanceResult(level, None, reasons, RelevanceSource.USER)


@dataclass(frozen=True)
class RelevanceRule:
    id: int
    goal_terms: tuple[str, ...]
    kind: TargetKind
    target: str
    level: RelevanceLevel

    @property
    def label(self) -> str:
        """What the rule is about, for lists ("youtube.com · SQL JOIN 실습")."""
        return " · ".join(p for p in self.target.split("\n") if p)


class RelevanceRules:
    """``relevance_rule`` table. The caller owns the connection and its thread."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, goal: str, data: RelevanceInput, level: RelevanceLevel) -> bool:
        aim = target(data)
        if aim is None:
            return False
        self.conn.execute(
            "INSERT INTO relevance_rule (goal_terms, target_kind, target, level, created_at_utc)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(goal_terms, target_kind, target)"
            " DO UPDATE SET level = excluded.level, created_at_utc = excluded.created_at_utc",
            (" ".join(rules.goal_terms(goal)), aim[0].value, aim[1], level.value, utc_now()),
        )
        return True

    def all(self) -> list[RelevanceRule]:
        rows = self.conn.execute(
            "SELECT id, goal_terms, target_kind, target, level FROM relevance_rule"
            " ORDER BY created_at_utc DESC, id DESC"
        ).fetchall()
        return [
            RelevanceRule(
                r[0], tuple(r[1].split()), TargetKind(r[2]), r[3], RelevanceLevel(r[4])
            )
            for r in rows
        ]

    def delete(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM relevance_rule WHERE id = ?", (rule_id,))

    def clear_pages(self) -> None:
        """Page-title consent withdrawn: rules that name a page title go with the titles."""
        self.conn.execute("DELETE FROM relevance_rule WHERE target_kind = 'PAGE'")


class FeedbackRules:
    """In-memory view of the rules for one goal, plus the answer for the current visit."""

    def __init__(self, goal: str = "", rule_list: list[RelevanceRule] | None = None) -> None:
        terms = set(rules.goal_terms(goal))
        self._rules: dict[tuple[TargetKind, str], RelevanceLevel] = {}
        for rule in rule_list or ():
            similar = terms & set(rule.goal_terms) or (not terms and not rule.goal_terms)
            if similar:
                self._rules.setdefault((rule.kind, rule.target), rule.level)  # newest first
        self._visit: tuple[tuple[str | None, ...], RelevanceLevel] | None = None

    def answer(self, data: RelevanceInput, level: RelevanceLevel) -> None:
        """The user's answer for what is in front right now."""
        self._visit = (_key(data), level)

    def lookup(self, data: RelevanceInput) -> TaskRelevanceResult | None:
        visit = self._visit
        if visit is not None:
            if visit[0] == _key(data):
                return user_result(visit[1])
            self._visit = None  # the activity changed: a one-time answer is used up
        if not self._rules:
            return None
        for kind, value in _targets(data):
            level = self._rules.get((kind, value))
            if level is not None:
                return user_result(level, rule=True)
        return None

    def forget_titles(self) -> None:
        self._visit = None
        self._rules = {k: v for k, v in self._rules.items() if k[0] is not TargetKind.PAGE}


def _key(data: RelevanceInput) -> tuple[str | None, ...]:
    return (data.process_name, data.domain, data.page_title)


def _targets(data: RelevanceInput) -> list[tuple[TargetKind, str]]:
    """Every rule target that could match, most specific first."""
    out = []
    if data.page_title:
        out.append(target(data))
    if data.domain:
        out.append((TargetKind.SITE, data.domain))
    if data.process_name and not data.domain:
        out.append((TargetKind.APP, data.process_name.strip().lower()))
    return out

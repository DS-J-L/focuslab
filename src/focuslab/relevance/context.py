"""Activity context: what came before, and for how long, can change what a page or tool means.

- A note-taking app, an AI assistant or an unexplained page opened right after task-related
  work (lecture -> notes, docs -> AI tool) is probably helping with it, and so is one the user
  keeps going back and forth to (docs -> AI -> docs -> AI).
- A title that reads closer to leisure than to the goal becomes POSSIBLY_UNRELATED only after
  it has stayed in front for a while.

To keep this from inferring too much: only rule or model evidence anchors a chain (a result
this module produced never does), blips shorter than ``min_visit_s`` are ignored, support
lasts at most ``support_max_s``, and any unobserved stretch (missing ticks, locked screen, no
input for ``away_idle_s``) clears the history instead of being bridged.
"""

from collections import deque
from dataclasses import dataclass, field

from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    RelevanceSource,
    TaskRelevanceResult,
)

# Results the context may turn into RELATED: nothing contradicts the goal, nothing proves it.
_SUPPORT_CANDIDATES = {RelevanceReason.SUPPORT_TOOL, RelevanceReason.NO_EVIDENCE}


@dataclass(frozen=True)
class ContextConfig:
    window_s: float = 600  # how far back patterns are looked for
    min_visit_s: float = 5  # shorter visits are blips: neither evidence nor support
    min_related_s: float = 20  # task-related work must last this long to anchor support
    support_max_s: float = 600  # a support tool is task-related at most this long per visit
    leisure_sustain_s: float = 180  # a leisure-like title in front this long is a deviation
    max_tick_gap_s: float = 5  # a longer silence between ticks is unobserved time
    away_idle_s: float = 120  # no input for this long may mean nobody is there


@dataclass
class _Visit:
    key: tuple[str | None, ...]
    start_ms: int
    end_ms: int
    base: TaskRelevanceResult
    related: bool = field(init=False)

    def __post_init__(self) -> None:
        self.related = self.base.level is RelevanceLevel.RELATED

    @property
    def seconds(self) -> float:
        return (self.end_ms - self.start_ms) / 1000


def _key(data: RelevanceInput) -> tuple[str | None, ...]:
    return (data.process_name, data.domain, data.page_title)


def _context(level: RelevanceLevel, reason: str, base: TaskRelevanceResult) -> TaskRelevanceResult:
    return TaskRelevanceResult(
        level, base.score, (reason, *base.reasons), RelevanceSource.CONTEXT, base.model_version
    )


class ActivityContext:
    """Per-session, in-memory, fed once per tick by the relevance engine."""

    def __init__(self, cfg: ContextConfig | None = None) -> None:
        self.cfg = cfg or ContextConfig()
        self.reset()

    def reset(self) -> None:
        self._history: deque[_Visit] = deque()  # closed visits, oldest first
        self._current: _Visit | None = None
        self._last_ms: int | None = None

    def update(
        self, data: RelevanceInput, base: TaskRelevanceResult, now_ms: int
    ) -> TaskRelevanceResult:
        cfg = self.cfg
        gap = self._last_ms is not None and now_ms - self._last_ms > cfg.max_tick_gap_s * 1000
        # Watching a page needs no input, so idle time alone does not end a page visit.
        away = data.idle_s is not None and data.idle_s >= cfg.away_idle_s and not data.page_title
        unobserved = base.source == RelevanceSource.INPUT
        if gap or unobserved or away:
            self.reset()
            if unobserved or away:
                return base
        self._last_ms = now_ms
        self._advance(_key(data), base, now_ms)
        return self._judge(self._current)

    def _advance(self, key: tuple[str | None, ...], base: TaskRelevanceResult, now: int) -> None:
        current = self._current
        if current is not None and current.key == key:
            current.end_ms = now
            current.base = base
            current.related = current.related or base.level is RelevanceLevel.RELATED
            return
        if current is not None and current.seconds >= self.cfg.min_visit_s:
            self._history.append(current)
        self._current = _Visit(key, now, now, base)  # starts when first observed
        horizon = now - self.cfg.window_s * 1000
        while self._history and self._history[0].end_ms < horizon:
            self._history.popleft()

    def visit_started_ms(self) -> int | None:
        """When the activity now in front came to the front (session clock)."""
        return self._current.start_ms if self._current is not None else None

    def _anchors(self, visit: _Visit) -> bool:
        return visit.related and visit.seconds >= self.cfg.min_related_s

    def _judge(self, visit: _Visit) -> TaskRelevanceResult:
        cfg, base = self.cfg, visit.base
        if base.level is not RelevanceLevel.UNCERTAIN:
            return base
        if RelevanceReason.TITLE_CLOSER_TO_LEISURE in base.reasons:
            if visit.seconds >= cfg.leisure_sustain_s and not self._alternates(visit.key):
                return _context(
                    RelevanceLevel.POSSIBLY_UNRELATED, RelevanceReason.SUSTAINED_LEISURE_LIKE, base
                )
            return base
        if not _SUPPORT_CANDIDATES.intersection(base.reasons) or visit.seconds > cfg.support_max_s:
            return base
        history = self._history
        # Blips between the two were dropped, so "right after" allows a blip-sized gap
        # (plus the tick between one visit's last observation and the next one's first).
        gap_ms = visit.start_ms - history[-1].end_ms if history else None
        right_after = gap_ms is not None and gap_ms <= (cfg.min_visit_s + 1) * 1000
        if right_after and self._anchors(history[-1]):
            return _context(RelevanceLevel.RELATED, RelevanceReason.FOLLOWS_RELATED_WORK, base)
        if self._alternates(visit.key):
            return _context(RelevanceLevel.RELATED, RelevanceReason.ALTERNATES_WITH_WORK, base)
        return base

    def _alternates(self, key: tuple[str | None, ...]) -> bool:
        """``key`` was used between two stretches of task-related work in the window."""
        visits = list(self._history)
        return any(
            visits[i].key == key and self._anchors(visits[i - 1]) and self._anchors(visits[i + 1])
            for i in range(1, len(visits) - 1)
        )

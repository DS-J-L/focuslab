"""Automatic work sessions detected from the activity timeline, without any user goal.

A session is a run of activity that is not broken by a long absence:
- an idle or locked span (or unobserved time) of at least ``break_split_s`` ends it;
  shorter ones are kept as interruptions;
- a different kind of work (category) that lasts ``switch_sustain_s`` starts a new session
  at the moment of the switch; a shorter excursion is a *detour* and the time until the
  user is back on the original kind is its return time.

Without a goal nothing is called "off task": detours are only observed switches. Sessions
are a grouping of spans, never added to any total, so they cannot double count time.
"""

from collections import Counter
from dataclasses import dataclass, field

from focuslab.activity.classifier import UserRules, effective
from focuslab.domain.activity import ActivitySpan, Category, ClassReason, SpanKind
from focuslab.i18n import tr

# Not evidence of any kind of work: desktop shell, FocusLab, unreadable programs.
_NEUTRAL_REASONS = {ClassReason.NEUTRAL_SHELL, ClassReason.UNREADABLE_APP, ClassReason.EXCLUDED}


@dataclass(frozen=True)
class AutoSessionConfig:
    break_split_s: float = 300
    switch_sustain_s: float = 300
    min_active_s: float = 120


@dataclass
class AutoSession:
    start_ms: int
    end_ms: int
    category: Category = Category.UNKNOWN
    active_ms: int = 0
    interrupted_ms: int = 0  # short idle/locked time inside the session
    switches: int = 0  # program/site changes between consecutive active spans
    detours: int = 0
    return_ms: list[int] = field(default_factory=list)  # one per detour that came back
    apps: dict[str, int] = field(default_factory=dict)  # display label -> active ms
    manual_session_id: int | None = None

    @property
    def mean_return_ms(self) -> float | None:
        return sum(self.return_ms) / len(self.return_ms) if self.return_ms else None


def span_label(span: ActivitySpan) -> str:
    """Program (and site) name for grouping; excluded spans have no name."""
    if span.excluded and not span.exe_name:
        return tr("Excluded")
    name = span.display_name or span.exe_name or tr("Unknown program")
    return f"{name} · {span.domain}" if span.domain else name


@dataclass
class _Builder:
    spans: list[tuple[ActivitySpan, Category | None]] = field(default_factory=list)
    kind: Category | None = None
    away_since: int | None = None  # index into spans where an excursion began
    away_ms: int = 0
    detours: int = 0
    return_ms: list[int] = field(default_factory=list)


def _clip(span: ActivitySpan, start_ms: int, end_ms: int) -> ActivitySpan | None:
    a, b = max(span.start_ms, start_ms), min(span.end_ms, end_ms)
    if b <= a:
        return None
    return ActivitySpan(**{**span.__dict__, "start_ms": a, "end_ms": b})


def detect_sessions(
    spans: list[ActivitySpan],
    user: UserRules | None = None,
    cfg: AutoSessionConfig | None = None,
    window: tuple[int, int] | None = None,
) -> list[AutoSession]:
    """Sessions in time order. ``window`` clips spans to ``[start, end)`` first."""
    cfg = cfg or AutoSessionConfig()
    user = user or UserRules.empty()
    split_ms, sustain_ms = cfg.break_split_s * 1000, cfg.switch_sustain_s * 1000
    if window:
        spans = [c for s in spans if (c := _clip(s, *window))]
    sessions: list[AutoSession] = []
    cur: _Builder | None = None
    last_end: int | None = None

    def finish() -> None:
        nonlocal cur
        if cur is not None:
            session = _summarize(cur)
            if session and session.active_ms >= cfg.min_active_s * 1000:
                sessions.append(session)
        cur = None

    for span in sorted(spans, key=lambda s: s.start_ms):
        if last_end is not None and span.start_ms - last_end >= split_ms:
            finish()  # not observed for a long time: FocusLab off, suspend, pause
        last_end = span.end_ms
        if span.kind is not SpanKind.ACTIVE:
            if span.duration_ms >= split_ms:
                finish()
            elif cur is not None:
                cur.spans.append((span, None))
            continue
        label = effective(span, user)
        kind = None if label.reason in _NEUTRAL_REASONS else label.category
        if cur is None:
            cur = _Builder()
        cur.spans.append((span, kind))
        if kind is None:
            continue
        if cur.kind is None:
            cur.kind = kind
        elif kind == cur.kind:
            if cur.away_since is not None:  # back to the original kind of work
                cur.detours += 1
                cur.return_ms.append(span.start_ms - cur.spans[cur.away_since][0].start_ms)
                cur.away_since, cur.away_ms = None, 0
        else:
            if cur.away_since is None:
                cur.away_since = len(cur.spans) - 1
            cur.away_ms += span.duration_ms
            if cur.away_ms >= sustain_ms:  # a new kind of work: split at the switch
                tail = cur.spans[cur.away_since :]
                cur.spans = cur.spans[: cur.away_since]
                cur.away_since = None
                finish()
                cur = _Builder(spans=tail)
                kinds = Counter()
                for s, k in tail:
                    if k is not None:
                        kinds[k] += s.duration_ms
                cur.kind = kinds.most_common(1)[0][0]
    finish()
    return sessions


def _summarize(builder: _Builder) -> AutoSession | None:
    items = list(builder.spans)
    while items and items[-1][0].kind is not SpanKind.ACTIVE:  # no trailing interruption
        items.pop()
    while items and items[0][0].kind is not SpanKind.ACTIVE:
        items.pop(0)
    if not items:
        return None
    session = AutoSession(items[0][0].start_ms, items[-1][0].end_ms)
    kinds: Counter[Category] = Counter()
    previous: str | None = None
    for span, kind in items:
        if span.kind is not SpanKind.ACTIVE:
            session.interrupted_ms += span.duration_ms
            continue
        session.active_ms += span.duration_ms
        if kind is not None:
            kinds[kind] += span.duration_ms
            label = span_label(span)
            session.apps[label] = session.apps.get(label, 0) + span.duration_ms
            if previous is not None and label != previous:
                session.switches += 1
            previous = label
    session.category = kinds.most_common(1)[0][0] if kinds else Category.UNKNOWN
    session.detours = builder.detours
    session.return_ms = builder.return_ms
    return session


def link_manual_sessions(sessions: list[AutoSession], manual: list[tuple[int, int, int]]) -> None:
    """Mark each automatic session with the manual focus session it overlaps most.

    ``manual`` holds ``(session_id, start_ms, end_ms)``. Overlapping time is the same time;
    reports show it once (from the activity timeline) and only label the overlap.
    """
    for session in sessions:
        best, best_overlap = None, 0
        for sid, start, end in manual:
            overlap = min(end, session.end_ms) - max(start, session.start_ms)
            if overlap > best_overlap:
                best, best_overlap = sid, overlap
        session.manual_session_id = best

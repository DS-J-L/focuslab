"""Activity statistics over a time window.

Every number is computed from the single, non-overlapping span timeline clipped to the
window, so per-program, per-site and per-category totals add up to the observed time and
can never exceed the real elapsed time. Focus sessions and automatic sessions are overlays
on this timeline, not extra time.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from focuslab.activity.auto_sessions import AutoSession, span_label
from focuslab.activity.camera_overlay import CameraOverlay, attended_ms
from focuslab.activity.classifier import Classification, UserRules, effective
from focuslab.activity.power import PowerReport
from focuslab.domain.activity import ActivitySpan, Category, ClassReason, SpanKind

# Categories that count as work when reporting "attended work time".
WORK = frozenset({
    Category.DEVELOPMENT, Category.STUDY, Category.DOCUMENTATION, Category.RESEARCH,
    Category.PRODUCTIVITY,
})
_NEUTRAL = {ClassReason.NEUTRAL_SHELL, ClassReason.UNREADABLE_APP, ClassReason.EXCLUDED}


@dataclass(frozen=True)
class LabeledSpan:
    span: ActivitySpan  # clipped to the window
    label: Classification
    camera: CameraOverlay | None = None


@dataclass
class ActivityStats:
    start_ms: int
    end_ms: int
    active_ms: int = 0
    idle_ms: int = 0
    locked_ms: int = 0
    by_category: Counter = field(default_factory=Counter)  # Category -> ms (idle/locked: BREAK)
    by_app: Counter = field(default_factory=Counter)  # program label -> active ms
    by_site: Counter = field(default_factory=Counter)  # hostname -> active ms
    by_page: Counter = field(default_factory=Counter)  # page title + site, or hostname fallback
    switches: int = 0
    transitions: Counter = field(default_factory=Counter)  # (from, to) -> count
    hourly_ms: list[int] = field(default_factory=lambda: [0] * 24)  # local hour -> active ms
    daily: dict[date, Counter] = field(default_factory=dict)  # local day -> Category -> ms
    work_ms: int = 0
    attended_work_ms: int = 0  # work minus camera-judged AWAY seconds
    camera_covered_ms: int = 0  # work time the camera actually observed
    sessions: list[AutoSession] = field(default_factory=list)
    manual_overlap_ms: int = 0  # activity time that falls inside manual focus sessions
    power: PowerReport | None = None  # PC power-on time, when the event log could tell

    @property
    def total_ms(self) -> int:
        """PC in use: active + idle (locked time is the PC not being used)."""
        return self.active_ms + self.idle_ms

    @property
    def observed_ms(self) -> int:
        return self.active_ms + self.idle_ms + self.locked_ms

    @property
    def mean_session_ms(self) -> float | None:
        if not self.sessions:
            return None
        return sum(s.active_ms for s in self.sessions) / len(self.sessions)

    @property
    def mean_return_ms(self) -> float | None:
        returns = [r for s in self.sessions for r in s.return_ms]
        return sum(returns) / len(returns) if returns else None


def clip(span: ActivitySpan, start_ms: int, end_ms: int) -> ActivitySpan | None:
    a, b = max(span.start_ms, start_ms), min(span.end_ms, end_ms)
    if b <= a:
        return None
    return ActivitySpan(**{**span.__dict__, "start_ms": a, "end_ms": b})


def label_spans(
    spans: Iterable[ActivitySpan],
    start_ms: int,
    end_ms: int,
    user: UserRules | None = None,
    camera: dict[int, CameraOverlay] | None = None,
) -> list[LabeledSpan]:
    user, camera = user or UserRules.empty(), camera or {}
    out = []
    for span in spans:
        clipped = clip(span, start_ms, end_ms)
        if clipped:
            out.append(LabeledSpan(clipped, effective(clipped, user), camera.get(span.span_id)))
    return out


def _split_by_hour(start_ms: int, end_ms: int) -> Iterable[tuple[datetime, int]]:
    t = start_ms
    while t < end_ms:
        local = datetime.fromtimestamp(t / 1000).astimezone()
        next_hour = (local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        stop = min(end_ms, int(next_hour.timestamp() * 1000))
        yield local, stop - t
        t = stop


def compute_stats(
    labeled: Sequence[LabeledSpan],
    start_ms: int,
    end_ms: int,
    sessions: Sequence[AutoSession] = (),
    manual: Sequence[tuple[int, int, int]] = (),
) -> ActivityStats:
    stats = ActivityStats(start_ms, end_ms, sessions=list(sessions))
    previous: str | None = None
    for item in sorted(labeled, key=lambda x: x.span.start_ms):
        span, label = item.span, item.label
        ms = span.duration_ms
        for local, part in _split_by_hour(span.start_ms, span.end_ms):
            stats.daily.setdefault(local.date(), Counter())[label.category] += part
            if span.kind is SpanKind.ACTIVE:
                stats.hourly_ms[local.hour] += part
        stats.by_category[label.category] += ms
        for _, m_start, m_end in manual:
            stats.manual_overlap_ms += max(0, min(m_end, span.end_ms) - max(m_start, span.start_ms))
        if span.kind is SpanKind.IDLE:
            stats.idle_ms += ms
            continue
        if span.kind is SpanKind.LOCKED:
            stats.locked_ms += ms
            continue
        stats.active_ms += ms
        name = span_label(span)
        stats.by_app[span.display_name or span.exe_name or name] += ms
        if span.domain:
            stats.by_site[span.domain] += ms
            page = f"{span.page_title} ({span.domain})" if span.page_title else span.domain
            stats.by_page[page] += ms
        if label.category in WORK:
            stats.work_ms += ms
            stats.attended_work_ms += attended_ms(span, item.camera)
            if item.camera:  # only the observed seconds, never the whole span
                stats.camera_covered_ms += min(ms, item.camera.camera_s * 1000)
        if label.reason in _NEUTRAL:
            continue
        if previous is not None and name != previous:
            stats.switches += 1
            stats.transitions[(previous, name)] += 1
        previous = name
    return stats


def local_day_bounds(day: date) -> tuple[int, int]:
    """UTC epoch ms of local midnight to the next local midnight (DST-safe)."""
    start = datetime.combine(day, datetime.min.time()).astimezone()
    end = datetime.combine(day + timedelta(days=1), datetime.min.time()).astimezone()
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)

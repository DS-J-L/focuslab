"""Session metrics (DEVELOPMENT_PLAN.md section 6). These are observed-activity estimates,
not a focus score: UNKNOWN, BREAK and AWAY are reported separately with coverage."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from statistics import mean

from focuslab.config import SELF_NAME
from focuslab.domain.events import StateSegment, build_segments
from focuslab.domain.models import FocusState, StateSample


@dataclass(frozen=True)
class SessionMetrics:
    measured_s: int
    seconds: dict[FocusState, int]
    on_task_ratio: float | None  # ON / (ON + POSSIBLY_OFF); None = not measurable
    coverage: float | None  # share of non-break seconds that were not UNKNOWN
    off_task_episodes: int
    mean_off_task_s: float | None
    return_gaps_s: tuple[int, ...]  # end of off-task episode -> next ON_TASK start
    mean_return_gap_s: float | None
    episodes_without_return: int
    app_switches: int
    longest_on_task_s: int
    corrected_segments: int = 0


def apply_corrections(
    samples: Sequence[StateSample], segments: Sequence[StateSegment]
) -> list[StateSample]:
    """Replace sample states inside corrected segments. Stored samples stay untouched."""
    ranges = [(s.start_s, s.end_s, s.corrected_label) for s in segments if s.corrected_label]
    if not ranges:
        return list(samples)
    out = []
    for sample in samples:
        label = next((lab for a, b, lab in ranges if a <= sample.second_offset < b), None)
        out.append(replace(sample, state=label) if label else sample)
    return out


def _app_switches(samples: Sequence[StateSample]) -> int:
    switches, last = 0, None
    for s in samples:
        if not s.app_name or s.app_name == SELF_NAME:
            continue
        if last is not None and s.app_name.lower() != last:
            switches += 1
        last = s.app_name.lower()
    return switches


def compute_metrics(samples: Sequence[StateSample], corrected_segments: int = 0) -> SessionMetrics:
    counts = Counter(s.state for s in samples)
    seconds = {state: counts.get(state, 0) for state in FocusState}
    on, off = seconds[FocusState.ON_TASK], seconds[FocusState.POSSIBLY_OFF_TASK]
    observed = len(samples) - seconds[FocusState.BREAK]

    segments = build_segments(samples)
    off_lengths: list[int] = []
    gaps: list[int] = []
    without_return = 0
    for i, seg in enumerate(segments):
        if seg.state is not FocusState.POSSIBLY_OFF_TASK:
            continue
        off_lengths.append(seg.duration_s)
        gap = None
        for later in segments[i + 1 :]:
            if later.state is FocusState.ON_TASK:
                gap = later.start_s - seg.end_s
                break
            if later.state in (FocusState.BREAK, FocusState.POSSIBLY_OFF_TASK):
                break
        if gap is None:
            without_return += 1
        else:
            gaps.append(gap)

    on_streaks = [s.duration_s for s in segments if s.state is FocusState.ON_TASK]
    return SessionMetrics(
        measured_s=len(samples),
        seconds=seconds,
        on_task_ratio=on / (on + off) if on + off else None,
        coverage=(observed - seconds[FocusState.UNKNOWN]) / observed if observed else None,
        off_task_episodes=len(off_lengths),
        mean_off_task_s=mean(off_lengths) if off_lengths else None,
        return_gaps_s=tuple(gaps),
        mean_return_gap_s=mean(gaps) if gaps else None,
        episodes_without_return=without_return,
        app_switches=_app_switches(samples),
        longest_on_task_s=max(on_streaks, default=0),
        corrected_segments=corrected_segments,
    )


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "측정 불가"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}시간 {m}분"
    if m:
        return f"{m}분 {s}초"
    return f"{s}초"


def format_ratio(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value * 100:.0f}%"

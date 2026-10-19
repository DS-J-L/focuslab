"""State segments: contiguous runs of one state, optionally corrected by the user."""

from collections.abc import Iterable
from dataclasses import dataclass

from focuslab.domain.models import FocusState, StateSample

# Severity shown in the timeline; only deviations are highlighted.
SEVERITY = {
    FocusState.ON_TASK: "info",
    FocusState.BREAK: "info",
    FocusState.UNKNOWN: "info",
    FocusState.POSSIBLY_OFF_TASK: "warning",
    FocusState.AWAY: "warning",
}


@dataclass(frozen=True)
class StateSegment:
    """One stored ``event`` row: ``[start_s, end_s)`` in active session seconds."""

    start_s: int
    end_s: int
    state: FocusState
    reason_codes: tuple[str, ...] = ()
    app_names: tuple[str, ...] = ()
    event_id: int | None = None
    corrected_label: FocusState | None = None

    @property
    def duration_s(self) -> int:
        return self.end_s - self.start_s

    @property
    def effective_state(self) -> FocusState:
        return self.corrected_label or self.state


def build_segments(samples: Iterable[StateSample]) -> list[StateSegment]:
    """Merge consecutive same-state samples. Gaps in offsets also split segments."""
    segments: list[StateSegment] = []
    start = end = None
    state: FocusState | None = None
    reasons: tuple[str, ...] = ()
    apps: list[str] = []
    for s in samples:
        if state is not None and s.state == state and s.second_offset == end:
            end += 1
            if s.app_name and s.app_name not in apps:
                apps.append(s.app_name)
            continue
        if state is not None:
            segments.append(StateSegment(start, end, state, reasons, tuple(apps)))
        start, end, state, reasons = s.second_offset, s.second_offset + 1, s.state, s.reason_codes
        apps = [s.app_name] if s.app_name else []
    if state is not None:
        segments.append(StateSegment(start, end, state, reasons, tuple(apps)))
    return segments

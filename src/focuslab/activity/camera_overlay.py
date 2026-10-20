"""Line up focus-session judgments (camera + PC) with the activity timeline.

The camera only runs inside focus sessions the user starts. For time covered by such a
session, each activity span gets counts of what the session engine observed. Only ``AWAY``
(face not visible *and* no input for a while) reduces attended time; looking elsewhere or
down is shown as an observation and never subtracted or called off-task.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from focuslab.domain.activity import ActivitySpan
from focuslab.domain.models import FocusState, StateSample
from focuslab.focus.metrics import apply_corrections
from focuslab.focus.reasons import Reason
from focuslab.storage.repository import Repository, epoch_ms


@dataclass
class CameraOverlay:
    session_ids: set[int]
    observed_s: int = 0  # seconds covered by a focus session
    camera_s: int = 0  # ... of which the camera was in use
    away_s: int = 0  # judged AWAY (face not visible + no input)
    face_absent_s: int = 0
    head_away_s: int = 0  # head turned away from the screen (observation only)
    head_down_s: int = 0  # looking down (observation only)

    @property
    def has_camera(self) -> bool:
        return self.camera_s > 0


def session_samples(
    repo: Repository, start_ms: int, end_ms: int
) -> list[tuple[int, int, StateSample]]:
    """``(at_ms, session_id, sample)`` of focus sessions overlapping the window, with the
    user's corrections applied. Samples from before schema v5 are placed at start + offset."""
    out = []
    for record in repo.list_sessions():
        started = epoch_ms(record.started_at_utc)
        ended = epoch_ms(record.ended_at_utc) if record.ended_at_utc else end_ms
        if ended < start_ms or started > end_ms:
            continue
        effective = apply_corrections(repo.samples(record.id), repo.segments(record.id))
        for sample in effective:
            at = sample.at_ms if sample.at_ms is not None else started + sample.second_offset * 1000
            if start_ms <= at < end_ms:
                out.append((at, record.id, sample))
    out.sort(key=lambda item: item[0])
    return out


def overlay(
    spans: Iterable[ActivitySpan], samples: list[tuple[int, int, StateSample]]
) -> dict[int, CameraOverlay]:
    """Per span id; spans without any focus-session second are absent."""
    result: dict[int, CameraOverlay] = {}
    ordered = sorted((s for s in spans if s.span_id is not None), key=lambda s: s.start_ms)
    i = 0
    for span in ordered:
        while i < len(samples) and samples[i][0] < span.start_ms:
            i += 1
        j = i
        while j < len(samples) and samples[j][0] < span.end_ms:
            at, sid, sample = samples[j]
            ov = result.setdefault(span.span_id, CameraOverlay(set()))
            ov.session_ids.add(sid)
            ov.observed_s += 1
            reasons = set(sample.reason_codes)
            if Reason.CAMERA_OFF not in reasons:
                ov.camera_s += 1
            if sample.state is FocusState.AWAY:
                ov.away_s += 1
            if Reason.FACE_NOT_VISIBLE in reasons:
                ov.face_absent_s += 1
            if Reason.HEAD_TURNED_AWAY in reasons:
                ov.head_away_s += 1
            if reasons & {Reason.HEAD_DOWN, Reason.HEAD_DOWN_READING}:
                ov.head_down_s += 1
            j += 1
    return result


def attended_ms(span: ActivitySpan, ov: CameraOverlay | None) -> int:
    """Active span time minus seconds the session engine judged AWAY."""
    if ov is None:
        return span.duration_ms
    return max(0, span.duration_ms - ov.away_s * 1000)

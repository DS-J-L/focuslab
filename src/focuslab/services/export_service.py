"""Local export (JSON/CSV) and deletion of the user's own records."""

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from focuslab import __version__
from focuslab.domain.events import StateSegment
from focuslab.domain.models import FocusState, SessionRecord, StateSample
from focuslab.focus.metrics import SessionMetrics, apply_corrections, compute_metrics
from focuslab.storage.repository import Repository


@dataclass(frozen=True)
class SessionReport:
    record: SessionRecord
    samples: list[StateSample]  # raw rule output
    effective: list[StateSample]  # with the user's corrections applied
    segments: list[StateSegment]
    metrics: SessionMetrics


def session_report(repo: Repository, session_id: int) -> SessionReport | None:
    record = repo.get_session(session_id)
    if record is None:
        return None
    samples = repo.samples(session_id)
    segments = repo.segments(session_id)
    effective = apply_corrections(samples, segments)
    corrected = sum(1 for s in segments if s.corrected_label)
    metrics = compute_metrics(effective, corrected)
    return SessionReport(record, samples, effective, segments, metrics)


def local_date(started_at_utc: str) -> date:
    return datetime.fromisoformat(started_at_utc).astimezone().date()


def daily_totals(
    repo: Repository, days: int = 7, today: date | None = None
) -> list[tuple[date, Counter[FocusState]]]:
    """Effective seconds per state for each of the last ``days`` local days."""
    today = today or datetime.now().astimezone().date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first - timedelta(days=1), datetime.min.time()).isoformat()
    totals: dict[date, Counter[FocusState]] = {
        first + timedelta(days=i): Counter() for i in range(days)
    }
    for record in repo.list_sessions(since_utc=since):
        day = local_date(record.started_at_utc)
        if day not in totals:
            continue
        samples = apply_corrections(repo.samples(record.id), repo.segments(record.id))
        totals[day].update(s.state for s in samples)
    return sorted(totals.items())


def _session_dict(report: SessionReport, repo: Repository) -> dict:
    record = asdict(report.record)
    metrics = asdict(report.metrics)
    metrics["seconds"] = {k.value: v for k, v in report.metrics.seconds.items()}
    return {
        "session": record,
        "metrics_after_corrections": metrics,
        "segments": [
            {
                "event_id": s.event_id,
                "start_s": s.start_s,
                "end_s": s.end_s,
                "state": s.state.value,
                "corrected_label": s.corrected_label.value if s.corrected_label else None,
                "reason_codes": list(s.reason_codes),
                "app_names": list(s.app_names),
            }
            for s in report.segments
        ],
        "feedback": [dict(row) for row in repo.feedback_rows(report.record.id)],
        "samples": [
            {
                "second_offset": raw.second_offset,
                "state": raw.state.value,
                "effective_state": eff.state.value,
                "confidence": raw.confidence,
                "reason_codes": list(raw.reason_codes),
                "app_name": raw.app_name,
            }
            for raw, eff in zip(report.samples, report.effective, strict=True)
        ],
    }


def _ids(repo: Repository, session_ids: list[int] | None) -> list[int]:
    if session_ids is not None:
        return session_ids
    return [s.id for s in reversed(repo.list_sessions())]


def export_json(repo: Repository, path: Path, session_ids: list[int] | None = None) -> Path:
    sessions = []
    for sid in _ids(repo, session_ids):
        report = session_report(repo, sid)
        if report:
            sessions.append(_session_dict(report, repo))
    payload = {
        "format": "focuslab-export",
        "app_version": __version__,
        "note": "관찰 가능한 행동의 추정치이며 집중력·의학적 상태의 측정값이 아닙니다.",
        "sessions": sessions,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


CSV_COLUMNS = [
    "session_id", "started_at_utc", "goal", "mode", "second_offset", "state",
    "effective_state", "confidence", "reason_codes", "app_name",
]


def export_csv(repo: Repository, path: Path, session_ids: list[int] | None = None) -> Path:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads Korean
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for sid in _ids(repo, session_ids):
            report = session_report(repo, sid)
            if not report:
                continue
            r = report.record
            for raw, eff in zip(report.samples, report.effective, strict=True):
                writer.writerow([
                    r.id, r.started_at_utc, r.goal, r.mode.value, raw.second_offset,
                    raw.state.value, eff.state.value, raw.confidence,
                    ";".join(raw.reason_codes), raw.app_name or "",
                ])
    return path


def delete_all(repo: Repository) -> None:
    """Delete every session and its derived data, then compact the file."""
    repo.delete_all_sessions()
    repo.conn.execute("VACUUM")

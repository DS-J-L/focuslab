"""Local export (JSON/CSV) and deletion of the user's own records."""

import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from focuslab import __version__
from focuslab.activity.camera_overlay import session_samples
from focuslab.activity.classifier import effective
from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import ActivitySpan
from focuslab.domain.events import StateSegment
from focuslab.domain.models import FocusState, SessionRecord, StateSample
from focuslab.focus.metrics import SessionMetrics, apply_corrections, compute_metrics
from focuslab.i18n import tr
from focuslab.services.activity_service import ALL_TIME, rebuild_auto_sessions
from focuslab.storage.activity_repository import ActivityRepository
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


def daily_totals(
    repo: Repository, days: int = 7, today: date | None = None
) -> list[tuple[date, Counter[FocusState]]]:
    """Effective seconds per state for each of the last ``days`` local days, by the time of
    each second: a session running past midnight counts on both days."""
    today = today or datetime.now().astimezone().date()
    first = today - timedelta(days=days - 1)
    totals: dict[date, Counter[FocusState]] = {
        first + timedelta(days=i): Counter() for i in range(days)
    }
    start_ms, _ = local_day_bounds(first)
    _, end_ms = local_day_bounds(today)
    for at, _, sample in session_samples(repo, start_ms, end_ms):
        totals[datetime.fromtimestamp(at / 1000).date()][sample.state] += 1
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


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def _span_row(span: ActivitySpan, rules) -> dict:
    label = effective(span, rules)
    return {
        "start_utc": _iso(span.start_ms),
        "end_utc": _iso(span.end_ms),
        "duration_s": round(span.duration_ms / 1000, 1),
        "kind": span.kind.value,
        "program": span.exe_name,
        "product_name": span.display_name,
        "site": span.domain,
        "page_title": span.page_title,
        "category": label.category.value,
        "confidence": round(label.confidence, 2),
        "reason": label.reason.value,
        "source": label.source.value,
        "stored_category": span.category.value if span.category else None,
        "user_category": span.user_category.value if span.user_category else None,
        "excluded": span.excluded,
    }


def activity_dict(repo: Repository) -> dict:
    """The whole activity record. Automatic sessions are rebuilt from the timeline and the
    current rules first, so the export never depends on which screens were opened."""
    activity = ActivityRepository(repo.conn)
    rules = activity.user_rules()
    apps, sites = activity.exclusions()
    return {
        "spans": [_span_row(s, rules) for s in activity.spans_between(*ALL_TIME)],
        "automatic_sessions": [
            {
                **{k: v for k, v in asdict(s).items() if k not in ("start_ms", "end_ms")},
                "start_utc": _iso(s.start_ms),
                "end_utc": _iso(s.end_ms),
                "category": s.category.value,
            }
            for s in rebuild_auto_sessions(repo.conn, *ALL_TIME)
        ],
        "system_events": [
            {"at_utc": _iso(r["at_ms"]), "type": r["type"], "detail": r["detail"]}
            for r in activity.events_between(*ALL_TIME)
        ],
        "classification_rules": [dict(r) for r in activity.rules()],
        "excluded_programs": sorted(apps),
        "excluded_sites": sorted(sites),
    }


def export_json(repo: Repository, path: Path, session_ids: list[int] | None = None) -> Path:
    """Sessions; a full export (no ``session_ids``) also contains the activity record."""
    sessions = []
    for sid in _ids(repo, session_ids):
        report = session_report(repo, sid)
        if report:
            sessions.append(_session_dict(report, repo))
    payload = {
        "format": "focuslab-export",
        "app_version": __version__,
        "note": tr(
            "Estimates of observable behavior, not measurements of attention or medical status."
        ),
        "sessions": sessions,
    }
    if session_ids is None:
        payload["activity"] = activity_dict(repo)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# Spreadsheet apps run a cell that starts with one of these as a formula. Page titles come from
# websites and product names from any program, so CSV cells get a leading quote instead.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value):
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


CSV_COLUMNS = [
    "session_id",
    "started_at_utc",
    "goal",
    "mode",
    "second_offset",
    "state",
    "effective_state",
    "confidence",
    "reason_codes",
    "app_name",
    "mode_name",
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
                writer.writerow(
                    _csv_cell(value)
                    for value in [
                        r.id,
                        r.started_at_utc,
                        r.goal,
                        r.mode.value,
                        raw.second_offset,
                        raw.state.value,
                        eff.state.value,
                        raw.confidence,
                        ";".join(raw.reason_codes),
                        raw.app_name or "",
                        r.mode_name or "",
                    ]
                )
    return path


ACTIVITY_CSV_COLUMNS = [
    "start_utc",
    "end_utc",
    "duration_s",
    "kind",
    "program",
    "product_name",
    "site",
    "page_title",
    "category",
    "confidence",
    "reason",
    "source",
    "stored_category",
    "user_category",
    "excluded",
]


def export_activity_csv(repo: Repository, path: Path) -> Path:
    activity = ActivityRepository(repo.conn)
    rules = activity.user_rules()
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, ACTIVITY_CSV_COLUMNS)
        writer.writeheader()
        for span in activity.spans_between(*ALL_TIME):
            writer.writerow({k: _csv_cell(v) for k, v in _span_row(span, rules).items()})
    return path


def apply_retention(repo: Repository, days: int, now: datetime | None = None) -> int:
    """Delete finished sessions and activity older than ``days`` (0 keeps everything)."""
    if days <= 0:
        return 0
    removed = repo.purge_older_than(days, now)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    ActivityRepository(repo.conn).purge_before(int(cutoff.timestamp() * 1000))
    return removed


def delete_all(repo: Repository) -> None:
    """Delete every session, every recorded activity and their derived data, then compact
    the file. Settings, consent, rules and exclusions are kept."""
    repo.delete_all_sessions()
    ActivityRepository(repo.conn).delete_all()
    repo.conn.execute("VACUUM")

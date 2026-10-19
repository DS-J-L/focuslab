"""Activity queries shared by the dashboard and exports: automatic sessions (rebuilt from the
timeline and stored) and the manual focus sessions they overlap."""

import json
import sqlite3
import time

from focuslab.activity.auto_sessions import (
    AutoSession,
    AutoSessionConfig,
    detect_sessions,
    link_manual_sessions,
)
from focuslab.activity.camera_overlay import overlay, session_samples
from focuslab.activity.stats import ActivityStats, LabeledSpan, compute_stats, label_spans
from focuslab.domain.activity import Category
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.repository import Repository, epoch_ms
from focuslab.storage.sqlite_db import transaction


def manual_session_ranges(
    repo: Repository, start_ms: int, end_ms: int
) -> list[tuple[int, int, int]]:
    now = time.time_ns() // 1_000_000
    out = []
    for record in repo.list_sessions():
        started = epoch_ms(record.started_at_utc)
        ended = epoch_ms(record.ended_at_utc) if record.ended_at_utc else now
        if ended > start_ms and started < end_ms:
            out.append((record.id, started, ended))
    return out


def rebuild_auto_sessions(
    conn: sqlite3.Connection, start_ms: int, end_ms: int, cfg: AutoSessionConfig | None = None
) -> list[AutoSession]:
    """Detect sessions in ``[start_ms, end_ms)`` and replace the stored ones starting there.

    The stored table is derived data: rebuilding is idempotent and follows later
    corrections, rules and exclusions.
    """
    activity = ActivityRepository(conn)
    spans = activity.spans_between(start_ms, end_ms)
    sessions = detect_sessions(spans, activity.user_rules(), cfg, window=(start_ms, end_ms))
    link_manual_sessions(sessions, manual_session_ranges(Repository(conn), start_ms, end_ms))
    with transaction(conn):
        conn.execute(
            "DELETE FROM auto_session WHERE start_ms >= ? AND start_ms < ?", (start_ms, end_ms)
        )
        conn.executemany(
            "INSERT INTO auto_session (start_ms, end_ms, category, active_ms, interrupted_ms,"
            " switches, detours, return_ms, apps, manual_session_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.start_ms, s.end_ms, s.category.value, s.active_ms, s.interrupted_ms,
                    s.switches, s.detours, ",".join(map(str, s.return_ms)),
                    json.dumps(s.apps, ensure_ascii=False), s.manual_session_id,
                )
                for s in sessions
            ],
        )
    return sessions


def activity_report(
    conn: sqlite3.Connection, start_ms: int, end_ms: int
) -> tuple[list[LabeledSpan], ActivityStats]:
    """Labeled spans (with camera overlay) and statistics for ``[start_ms, end_ms)``.

    Rebuilds the automatic sessions of the window so they follow the latest corrections.
    """
    activity, repo = ActivityRepository(conn), Repository(conn)
    spans = activity.spans_between(start_ms, end_ms)
    camera = overlay(spans, session_samples(repo, start_ms, end_ms))
    labeled = label_spans(spans, start_ms, end_ms, activity.user_rules(), camera)
    sessions = rebuild_auto_sessions(conn, start_ms, end_ms)
    manual = manual_session_ranges(repo, start_ms, end_ms)
    return labeled, compute_stats(labeled, start_ms, end_ms, sessions, manual)


def stored_auto_sessions(
    conn: sqlite3.Connection, start_ms: int, end_ms: int
) -> list[AutoSession]:
    rows = conn.execute(
        "SELECT * FROM auto_session WHERE start_ms >= ? AND start_ms < ? ORDER BY start_ms",
        (start_ms, end_ms),
    ).fetchall()
    return [
        AutoSession(
            r["start_ms"], r["end_ms"], Category(r["category"]), r["active_ms"],
            r["interrupted_ms"], r["switches"], r["detours"],
            [int(x) for x in r["return_ms"].split(",") if x], json.loads(r["apps"]),
            r["manual_session_id"],
        )
        for r in rows
    ]

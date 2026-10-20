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
from focuslab.domain.activity import Category, SpanKind
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.repository import Repository, epoch_ms
from focuslab.storage.sqlite_db import transaction

ALL_TIME = (0, 2**62)


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


def _starts_afresh(prev: tuple[int, int, SpanKind], next_start_ms: int, split_ms: float) -> bool:
    """Whether ``detect_sessions`` starts over after ``prev``: a long unobserved gap or a long
    idle/locked span. What comes after such a point never depends on what came before."""
    start, end, kind = prev
    return next_start_ms - end >= split_ms or (
        kind is not SpanKind.ACTIVE and end - start >= split_ms
    )


def detection_bounds(
    activity: ActivityRepository, start_ms: int, end_ms: int, split_ms: float
) -> tuple[int, int]:
    """Widen ``[start_ms, end_ms)`` to the nearest points where session detection starts over,
    so a session crossing the window edge is detected whole, whatever window is asked for."""
    lo, later = ALL_TIME[0], None
    for span in activity.span_extents(start_ms, before=True):
        if later is not None and _starts_afresh(span, later[0], split_ms):
            lo = later[0]
            break
        later = span
    hi, prev = ALL_TIME[1], next(activity.span_extents(end_ms, before=True), None)
    for span in activity.span_extents(end_ms, before=False):
        if prev is not None and _starts_afresh(prev, span[0], split_ms):
            hi = span[0]
            break
        prev = span
    return lo, hi


def rebuild_auto_sessions(
    conn: sqlite3.Connection, start_ms: int, end_ms: int, cfg: AutoSessionConfig | None = None
) -> list[AutoSession]:
    """Detect and store the automatic sessions overlapping ``[start_ms, end_ms)``.

    Detection runs over whole stretches of activity (see ``detection_bounds``), never over
    spans clipped to the window, so a session crossing midnight is stored once and is the
    same for a day, a week or a month view. The stored table is derived data: rebuilding is
    idempotent and follows later corrections, rules and exclusions.
    """
    cfg = cfg or AutoSessionConfig()
    activity = ActivityRepository(conn)
    lo, hi = detection_bounds(activity, start_ms, end_ms, cfg.break_split_s * 1000)
    sessions = detect_sessions(activity.spans_between(lo, hi), activity.user_rules(), cfg)
    link_manual_sessions(sessions, manual_session_ranges(Repository(conn), lo, hi))
    with transaction(conn):
        conn.execute("DELETE FROM auto_session WHERE end_ms > ? AND start_ms < ?", (lo, hi))
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
    return [s for s in sessions if s.end_ms > start_ms and s.start_ms < end_ms]


def activity_report(
    conn: sqlite3.Connection, start_ms: int, end_ms: int
) -> tuple[list[LabeledSpan], ActivityStats]:
    """Labeled spans (with camera overlay) and statistics for ``[start_ms, end_ms)``.

    Rebuilds the automatic sessions overlapping the window so they follow the latest
    corrections. A session crossing the window edge is listed whole.
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
    """Stored sessions overlapping ``[start_ms, end_ms)``, as last rebuilt."""
    rows = conn.execute(
        "SELECT * FROM auto_session WHERE end_ms > ? AND start_ms < ? ORDER BY start_ms",
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

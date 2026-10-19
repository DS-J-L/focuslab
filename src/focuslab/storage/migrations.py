"""Schema versions. Each migration runs once inside a transaction and is recorded."""

import sqlite3
from datetime import UTC, datetime

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE session (
            id INTEGER PRIMARY KEY,
            goal TEXT NOT NULL,
            mode TEXT NOT NULL,
            planned_minutes INTEGER NOT NULL DEFAULT 0,
            started_at_utc TEXT NOT NULL,
            ended_at_utc TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('RUNNING', 'PAUSED', 'FINISHED', 'INTERRUPTED')),
            camera_enabled INTEGER NOT NULL,
            rule_version TEXT NOT NULL,
            paused_seconds INTEGER NOT NULL DEFAULT 0,
            self_report TEXT
        );
        CREATE TABLE session_allowed_app (
            session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
            process_name TEXT NOT NULL,
            display_label TEXT,
            PRIMARY KEY (session_id, process_name)
        );
        CREATE TABLE state_sample (
            session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
            second_offset INTEGER NOT NULL,
            state TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason_codes TEXT NOT NULL DEFAULT '',
            app_name TEXT,
            PRIMARY KEY (session_id, second_offset)
        );
        CREATE TABLE event (
            id INTEGER PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
            started_offset_ms INTEGER NOT NULL,
            ended_offset_ms INTEGER NOT NULL,
            type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason_codes TEXT NOT NULL DEFAULT '',
            app_names TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL
        );
        CREATE INDEX event_session ON event(session_id, started_offset_ms);
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL UNIQUE REFERENCES event(id) ON DELETE CASCADE,
            corrected_label TEXT NOT NULL,
            comment TEXT,
            created_at_utc TEXT NOT NULL
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );
        """,
    ),
]


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS migration (version INTEGER PRIMARY KEY, applied_at_utc TEXT)"
    )
    row = conn.execute("SELECT MAX(version) FROM migration").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; a failing migration rolls back and leaves data untouched."""
    version = current_version(conn)
    for target, sql in MIGRATIONS:
        if target <= version:
            continue
        conn.execute("BEGIN")
        try:
            for statement in filter(str.strip, sql.split(";")):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO migration (version, applied_at_utc) VALUES (?, ?)",
                (target, datetime.now(UTC).isoformat(timespec="seconds")),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version = target
    return version

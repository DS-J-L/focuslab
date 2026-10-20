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
    (
        2,
        # Always-on activity recording: one row per executable identity and a timeline of
        # non-overlapping spans in UTC epoch ms. Unobserved time has no row.
        """
        CREATE TABLE app (
            id INTEGER PRIMARY KEY,
            exe_name TEXT NOT NULL UNIQUE,
            display_name TEXT,
            first_seen_utc TEXT NOT NULL
        );
        CREATE TABLE activity_span (
            id INTEGER PRIMARY KEY,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('ACTIVE', 'IDLE', 'LOCKED')),
            app_id INTEGER REFERENCES app(id),
            CHECK (end_ms >= start_ms)
        );
        CREATE INDEX activity_span_start ON activity_span(start_ms);
        CREATE INDEX activity_span_end ON activity_span(end_ms);
        CREATE TABLE system_event (
            id INTEGER PRIMARY KEY,
            at_ms INTEGER NOT NULL,
            type TEXT NOT NULL,
            detail TEXT
        );
        CREATE INDEX system_event_at ON system_event(at_ms);
        """,
    ),
    (
        3,
        # Browser extension bridge: the latest state per browser profile (written by the native
        # messaging host, read by the recorder) and the site hostname of browser spans.
        """
        CREATE TABLE browser_state (
            browser TEXT NOT NULL,
            instance TEXT NOT NULL,
            seq INTEGER NOT NULL,
            focused INTEGER NOT NULL,
            domain TEXT,
            updated_ms INTEGER NOT NULL,
            PRIMARY KEY (browser, instance)
        );
        ALTER TABLE activity_span ADD COLUMN domain TEXT;
        CREATE INDEX activity_span_domain ON activity_span(domain) WHERE domain IS NOT NULL;
        """,
    ),
    (
        4,
        # Classification stored with each span, rules the user created from corrections and
        # per-span corrections (one per span, like ``feedback`` for state segments).
        """
        ALTER TABLE activity_span ADD COLUMN category TEXT;
        ALTER TABLE activity_span ADD COLUMN confidence REAL;
        ALTER TABLE activity_span ADD COLUMN reason TEXT;
        ALTER TABLE activity_span ADD COLUMN source TEXT;
        ALTER TABLE activity_span ADD COLUMN classified_ms INTEGER;
        ALTER TABLE activity_span ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;
        CREATE TABLE classification_rule (
            id INTEGER PRIMARY KEY,
            match_type TEXT NOT NULL CHECK (match_type IN ('app', 'site')),
            pattern TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            UNIQUE (match_type, pattern)
        );
        CREATE TABLE activity_feedback (
            id INTEGER PRIMARY KEY,
            span_id INTEGER NOT NULL UNIQUE REFERENCES activity_span(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            created_at_utc TEXT NOT NULL
        );
        """,
    ),
    (
        5,
        # Automatic sessions (derived from activity_span, rebuilt on demand) and the wall time
        # of focus-session samples so camera observations line up with the activity timeline.
        """
        CREATE TABLE auto_session (
            id INTEGER PRIMARY KEY,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            category TEXT NOT NULL,
            active_ms INTEGER NOT NULL,
            interrupted_ms INTEGER NOT NULL,
            switches INTEGER NOT NULL,
            detours INTEGER NOT NULL,
            return_ms TEXT NOT NULL DEFAULT '',
            apps TEXT NOT NULL DEFAULT '{}',
            manual_session_id INTEGER REFERENCES session(id) ON DELETE SET NULL,
            CHECK (end_ms >= start_ms)
        );
        CREATE INDEX auto_session_start ON auto_session(start_ms);
        ALTER TABLE state_sample ADD COLUMN at_ms INTEGER;
        CREATE INDEX state_sample_at ON state_sample(at_ms) WHERE at_ms IS NOT NULL;
        """,
    ),
    (
        6,
        # Separate, opt-in browser page titles. Old records remain title-less.
        """
        ALTER TABLE browser_state ADD COLUMN page_title TEXT;
        ALTER TABLE activity_span ADD COLUMN page_title TEXT;
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

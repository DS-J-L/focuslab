"""Sessions, per-second state samples, state segments, corrections and settings."""

import sqlite3
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from focuslab.domain.events import SEVERITY, StateSegment
from focuslab.domain.models import (
    FocusState,
    SessionConfig,
    SessionMode,
    SessionRecord,
    SessionStatus,
    StateSample,
)
from focuslab.storage.sqlite_db import transaction


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def epoch_ms(iso_utc: str) -> int:
    """Stored ISO timestamp (``utc_now``) to UTC epoch milliseconds."""
    return int(datetime.fromisoformat(iso_utc).timestamp() * 1000)


def _join(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(v for v in (value or "").split(",") if v)


class Repository:
    """Thin data access layer. The caller owns the connection and its thread."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def transaction(self) -> AbstractContextManager[None]:
        return transaction(self.conn)

    # sessions -----------------------------------------------------------------
    def create_session(
        self, config: SessionConfig, rule_version: str, started_at_utc: str | None = None
    ) -> int:
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO session (goal, mode, planned_minutes, started_at_utc, status,"
                " camera_enabled, rule_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    config.goal, config.mode.value, config.planned_minutes,
                    started_at_utc or utc_now(), SessionStatus.RUNNING.value,
                    int(config.camera_enabled), rule_version,
                ),
            )
            session_id = cur.lastrowid
            self.conn.executemany(
                "INSERT OR IGNORE INTO session_allowed_app (session_id, process_name)"
                " VALUES (?, ?)",
                [(session_id, app.lower()) for app in config.allowed_apps],
            )
        return session_id

    def set_status(
        self, session_id: int, status: SessionStatus, ended_at_utc: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE session SET status = ?, ended_at_utc = COALESCE(?, ended_at_utc)"
            " WHERE id = ?",
            (status.value, ended_at_utc, session_id),
        )

    def add_paused_seconds(self, session_id: int, seconds: int) -> None:
        self.conn.execute(
            "UPDATE session SET paused_seconds = paused_seconds + ? WHERE id = ?",
            (seconds, session_id),
        )

    def set_self_report(self, session_id: int, value: str | None) -> None:
        self.conn.execute("UPDATE session SET self_report = ? WHERE id = ?", (value, session_id))

    def _record(self, row: sqlite3.Row) -> SessionRecord:
        apps = self.conn.execute(
            "SELECT process_name FROM session_allowed_app WHERE session_id = ?"
            " ORDER BY process_name",
            (row["id"],),
        ).fetchall()
        return SessionRecord(
            id=row["id"],
            goal=row["goal"],
            mode=SessionMode(row["mode"]),
            planned_minutes=row["planned_minutes"],
            started_at_utc=row["started_at_utc"],
            ended_at_utc=row["ended_at_utc"],
            status=SessionStatus(row["status"]),
            camera_enabled=bool(row["camera_enabled"]),
            rule_version=row["rule_version"],
            paused_seconds=row["paused_seconds"],
            self_report=row["self_report"],
            allowed_apps=tuple(a["process_name"] for a in apps),
        )

    def get_session(self, session_id: int) -> SessionRecord | None:
        row = self.conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
        return self._record(row) if row else None

    def list_sessions(
        self, since_utc: str | None = None, limit: int | None = None
    ) -> list[SessionRecord]:
        sql = (
            "SELECT * FROM session WHERE started_at_utc >= ?"
            " ORDER BY started_at_utc DESC, id DESC"
        )
        params: list[object] = [since_utc or ""]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [self._record(r) for r in self.conn.execute(sql, params).fetchall()]

    def recover_interrupted(self) -> list[int]:
        """Mark sessions left RUNNING/PAUSED by a crash as INTERRUPTED. Data is kept."""
        rows = self.conn.execute(
            "SELECT s.id, s.started_at_utc, s.paused_seconds,"
            " (SELECT COUNT(*) FROM state_sample WHERE session_id = s.id) AS n"
            " FROM session s WHERE status IN ('RUNNING', 'PAUSED')"
        ).fetchall()
        for row in rows:
            started = datetime.fromisoformat(row["started_at_utc"])
            # Best estimate of the end: observed seconds plus recorded pauses.
            ended = started + timedelta(seconds=row["n"] + row["paused_seconds"])
            self.set_status(
                row["id"], SessionStatus.INTERRUPTED, ended.isoformat(timespec="seconds")
            )
        return [row["id"] for row in rows]

    # samples --------------------------------------------------------------------
    def add_sample(self, session_id: int, sample: StateSample) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state_sample (session_id, second_offset, state, confidence,"
            " reason_codes, app_name, at_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, sample.second_offset, sample.state.value,
                round(sample.confidence, 3), _join(sample.reason_codes), sample.app_name,
                sample.at_ms,
            ),
        )

    def samples(self, session_id: int) -> list[StateSample]:
        rows = self.conn.execute(
            "SELECT * FROM state_sample WHERE session_id = ? ORDER BY second_offset",
            (session_id,),
        ).fetchall()
        return [
            StateSample(
                r["second_offset"], FocusState(r["state"]), r["confidence"],
                _split(r["reason_codes"]), r["app_name"], r["at_ms"],
            )
            for r in rows
        ]

    # segments -------------------------------------------------------------------
    def insert_segment(self, session_id: int, segment: StateSegment, source: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO event (session_id, started_offset_ms, ended_offset_ms, type, severity,"
            " reason_codes, app_names, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, segment.start_s * 1000, segment.end_s * 1000, segment.state.value,
                SEVERITY[segment.state], _join(segment.reason_codes),
                _join(segment.app_names), source,
            ),
        )
        return cur.lastrowid

    def extend_segment(self, event_id: int, end_s: int, app_names: tuple[str, ...]) -> None:
        self.conn.execute(
            "UPDATE event SET ended_offset_ms = ?, app_names = ? WHERE id = ?",
            (end_s * 1000, _join(app_names), event_id),
        )

    def segments(self, session_id: int) -> list[StateSegment]:
        rows = self.conn.execute(
            "SELECT e.*, f.corrected_label FROM event e LEFT JOIN feedback f ON f.event_id = e.id"
            " WHERE e.session_id = ? ORDER BY e.started_offset_ms",
            (session_id,),
        ).fetchall()
        return [
            StateSegment(
                start_s=r["started_offset_ms"] // 1000,
                end_s=r["ended_offset_ms"] // 1000,
                state=FocusState(r["type"]),
                reason_codes=_split(r["reason_codes"]),
                app_names=_split(r["app_names"]),
                event_id=r["id"],
                corrected_label=FocusState(r["corrected_label"]) if r["corrected_label"] else None,
            )
            for r in rows
        ]

    # feedback -------------------------------------------------------------------
    def set_feedback(self, event_id: int, label: FocusState, comment: str | None = None) -> None:
        """One correction per event; a newer correction replaces the older one."""
        self.conn.execute(
            "INSERT INTO feedback (event_id, corrected_label, comment, created_at_utc)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(event_id) DO UPDATE SET"
            " corrected_label = excluded.corrected_label, comment = excluded.comment,"
            " created_at_utc = excluded.created_at_utc",
            (event_id, label.value, comment, utc_now()),
        )

    def clear_feedback(self, event_id: int) -> None:
        self.conn.execute("DELETE FROM feedback WHERE event_id = ?", (event_id,))

    def feedback_rows(self, session_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT f.* FROM feedback f JOIN event e ON e.id = f.event_id"
            " WHERE e.session_id = ? ORDER BY f.id",
            (session_id,),
        ).fetchall()

    # settings -------------------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value, updated_at_utc) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at_utc = excluded.updated_at_utc",
            (key, value, utc_now()),
        )

    def delete_setting(self, key: str) -> None:
        self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    # deletion -------------------------------------------------------------------
    def delete_session(self, session_id: int) -> None:
        self.conn.execute("DELETE FROM session WHERE id = ?", (session_id,))

    def delete_all_sessions(self) -> None:
        self.conn.execute("DELETE FROM session")

    def purge_older_than(self, days: int, now: datetime | None = None) -> int:
        """Delete finished sessions that started more than ``days`` ago. 0 keeps everything."""
        if days <= 0:
            return 0
        cutoff = ((now or datetime.now(UTC)) - timedelta(days=days)).isoformat(
            timespec="seconds"
        )
        cur = self.conn.execute(
            "DELETE FROM session WHERE started_at_utc < ?"
            " AND status IN ('FINISHED', 'INTERRUPTED')",
            (cutoff,),
        )
        return cur.rowcount

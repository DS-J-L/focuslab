"""Activity spans, program identities and system events of the always-on recorder."""

import sqlite3
from collections.abc import Iterable
from contextlib import AbstractContextManager

from focuslab.domain.activity import ActivitySpan, SpanKind
from focuslab.storage.repository import utc_now
from focuslab.storage.sqlite_db import transaction

_SPAN_SELECT = (
    "SELECT s.id, s.start_ms, s.end_ms, s.kind, a.exe_name, a.display_name"
    " FROM activity_span s LEFT JOIN app a ON a.id = s.app_id"
)


def _span(row: sqlite3.Row) -> ActivitySpan:
    return ActivitySpan(
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        kind=SpanKind(row["kind"]),
        exe_name=row["exe_name"],
        display_name=row["display_name"],
        span_id=row["id"],
    )


class ActivityRepository:
    """The caller owns the connection and its thread, like ``Repository``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._app_ids: dict[tuple[str, str | None], int] = {}

    def transaction(self) -> AbstractContextManager[None]:
        return transaction(self.conn)

    # programs -------------------------------------------------------------------
    def app_id(self, exe_name: str, display_name: str | None = None) -> int:
        cached = self._app_ids.get((exe_name, display_name))
        if cached is not None:
            return cached
        self.conn.execute(
            "INSERT OR IGNORE INTO app (exe_name, display_name, first_seen_utc) VALUES (?, ?, ?)",
            (exe_name, display_name, utc_now()),
        )
        if display_name:  # an app first seen without version info gets its name later
            self.conn.execute(
                "UPDATE app SET display_name = ? WHERE exe_name = ? AND display_name IS NULL",
                (display_name, exe_name),
            )
        row = self.conn.execute("SELECT id FROM app WHERE exe_name = ?", (exe_name,)).fetchone()
        self._app_ids[(exe_name, display_name)] = row["id"]
        return row["id"]

    # spans ----------------------------------------------------------------------
    def insert_span(self, span: ActivitySpan) -> int:
        app = self.app_id(span.exe_name, span.display_name) if span.exe_name else None
        cur = self.conn.execute(
            "INSERT INTO activity_span (start_ms, end_ms, kind, app_id) VALUES (?, ?, ?, ?)",
            (span.start_ms, span.end_ms, span.kind.value, app),
        )
        return cur.lastrowid

    def update_span_end(self, span_id: int, end_ms: int) -> None:
        self.conn.execute("UPDATE activity_span SET end_ms = ? WHERE id = ?", (end_ms, span_id))

    def spans_between(self, start_ms: int, end_ms: int) -> list[ActivitySpan]:
        """Spans overlapping ``[start_ms, end_ms)``, unclipped, in time order."""
        rows = self.conn.execute(
            _SPAN_SELECT + " WHERE s.end_ms > ? AND s.start_ms < ? ORDER BY s.start_ms, s.id",
            (start_ms, end_ms),
        ).fetchall()
        return [_span(r) for r in rows]

    def last_span(self) -> ActivitySpan | None:
        row = self.conn.execute(_SPAN_SELECT + " ORDER BY s.end_ms DESC LIMIT 1").fetchone()
        return _span(row) if row else None

    # system events --------------------------------------------------------------
    def add_events(self, events: Iterable[tuple[int, str, str | None]]) -> None:
        self.conn.executemany(
            "INSERT INTO system_event (at_ms, type, detail) VALUES (?, ?, ?)", list(events)
        )

    def events_between(self, start_ms: int, end_ms: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM system_event WHERE at_ms >= ? AND at_ms < ? ORDER BY at_ms, id",
            (start_ms, end_ms),
        ).fetchall()

    def last_event(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM system_event ORDER BY at_ms DESC, id DESC LIMIT 1"
        ).fetchone()

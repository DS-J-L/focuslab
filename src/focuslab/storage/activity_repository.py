"""Activity spans, program identities, system events, classification rules and corrections."""

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager

from focuslab.activity.classifier import UserRules
from focuslab.domain.activity import ActivitySpan, Category, ClassReason, ClassSource, SpanKind
from focuslab.storage.repository import utc_now
from focuslab.storage.sqlite_db import transaction

_SPAN_SELECT = (
    "SELECT s.id, s.start_ms, s.end_ms, s.kind, s.domain, s.page_title,"
    " s.category, s.confidence, s.reason,"
    " s.source, s.excluded, a.exe_name, a.display_name, f.category AS user_category"
    " FROM activity_span s LEFT JOIN app a ON a.id = s.app_id"
    " LEFT JOIN activity_feedback f ON f.span_id = s.id"
)

EXCLUDED_APPS = "privacy.excluded_apps"
EXCLUDED_SITES = "privacy.excluded_sites"


def _enum(kind, value):
    return kind(value) if value else None


def _span(row: sqlite3.Row) -> ActivitySpan:
    return ActivitySpan(
        start_ms=row["start_ms"],
        end_ms=row["end_ms"],
        kind=SpanKind(row["kind"]),
        exe_name=row["exe_name"],
        display_name=row["display_name"],
        span_id=row["id"],
        domain=row["domain"],
        page_title=row["page_title"],
        category=_enum(Category, row["category"]),
        confidence=row["confidence"],
        reason=_enum(ClassReason, row["reason"]),
        source=_enum(ClassSource, row["source"]),
        excluded=bool(row["excluded"]),
        user_category=_enum(Category, row["user_category"]),
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
    def insert_span(self, span: ActivitySpan, classified_ms: int | None = None) -> int:
        app = self.app_id(span.exe_name, span.display_name) if span.exe_name else None
        cur = self.conn.execute(
            "INSERT INTO activity_span "
            "(start_ms, end_ms, kind, app_id, domain, page_title, category,"
            " confidence, reason, source, classified_ms, excluded)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                span.start_ms, span.end_ms, span.kind.value, app, span.domain, span.page_title,
                span.category and span.category.value, span.confidence,
                span.reason and span.reason.value, span.source and span.source.value,
                classified_ms if span.category else None, int(span.excluded),
            ),
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

    def span_extents(self, at_ms: int, before: bool) -> Iterator[tuple[int, int, SpanKind]]:
        """``(start_ms, end_ms, kind)`` of the spans starting before ``at_ms`` (latest first)
        or at/after it (earliest first), read lazily so the caller can stop early."""
        op, order = ("<", "DESC") if before else (">=", "ASC")
        cursor = self.conn.execute(
            f"SELECT start_ms, end_ms, kind FROM activity_span WHERE start_ms {op} ?"
            f" ORDER BY start_ms {order}, id {order}",
            (at_ms,),
        )
        try:
            for start_ms, end_ms, kind in cursor:
                yield start_ms, end_ms, SpanKind(kind)
        finally:
            cursor.close()

    def browser_detail(self, browser: str, since_ms: int) -> tuple[str | None, str | None]:
        """Latest browser site and optionally permitted page title."""
        row = self.conn.execute(
            "SELECT domain, page_title FROM browser_state WHERE browser = ? AND focused = 1"
            " AND updated_ms >= ? ORDER BY updated_ms DESC LIMIT 1",
            (browser, since_ms),
        ).fetchone()
        return (row["domain"], row["page_title"]) if row else (None, None)

    def browser_domain(self, browser: str, since_ms: int) -> str | None:
        return self.browser_detail(browser, since_ms)[0]

    def last_span(self) -> ActivitySpan | None:
        row = self.conn.execute(_SPAN_SELECT + " ORDER BY s.end_ms DESC LIMIT 1").fetchone()
        return _span(row) if row else None

    # corrections and rules ------------------------------------------------------
    def set_span_category(self, span_id: int, category: Category) -> None:
        """Correct one span; a newer correction replaces the older one."""
        self.conn.execute(
            "INSERT INTO activity_feedback (span_id, category, created_at_utc) VALUES (?, ?, ?)"
            " ON CONFLICT(span_id) DO UPDATE SET category = excluded.category,"
            " created_at_utc = excluded.created_at_utc",
            (span_id, category.value, utc_now()),
        )

    def clear_span_category(self, span_id: int) -> None:
        self.conn.execute("DELETE FROM activity_feedback WHERE span_id = ?", (span_id,))

    def set_rule(self, match_type: str, pattern: str, category: Category) -> None:
        """``match_type`` is ``app`` (executable) or ``site`` (hostname suffix)."""
        self.conn.execute(
            "INSERT INTO classification_rule (match_type, pattern, category, created_at_utc)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(match_type, pattern) DO UPDATE SET"
            " category = excluded.category, created_at_utc = excluded.created_at_utc",
            (match_type, pattern.strip().lower(), category.value, utc_now()),
        )

    def delete_rule(self, match_type: str, pattern: str) -> None:
        self.conn.execute(
            "DELETE FROM classification_rule WHERE match_type = ? AND pattern = ?",
            (match_type, pattern),
        )

    def rules(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM classification_rule ORDER BY match_type, pattern"
        ).fetchall()

    def user_rules(self) -> UserRules:
        apps, sites = {}, {}
        for row in self.rules():
            target = apps if row["match_type"] == "app" else sites
            target[row["pattern"]] = Category(row["category"])
        return UserRules(apps, sites)

    # exclusions -------------------------------------------------------------------
    def _setting_list(self, key: str) -> frozenset[str]:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        try:
            return frozenset(json.loads(row["value"])) if row else frozenset()
        except (ValueError, TypeError):
            return frozenset()

    def exclusions(self) -> tuple[frozenset[str], frozenset[str]]:
        """(excluded executables, excluded hostname suffixes)."""
        return self._setting_list(EXCLUDED_APPS), self._setting_list(EXCLUDED_SITES)

    def set_exclusions(self, apps: Iterable[str], sites: Iterable[str]) -> None:
        for key, values in ((EXCLUDED_APPS, apps), (EXCLUDED_SITES, sites)):
            cleaned = sorted({v.strip().lower() for v in values if v.strip()})
            self.conn.execute(
                "INSERT INTO settings (key, value, updated_at_utc) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at_utc = excluded.updated_at_utc",
                (key, json.dumps(cleaned), utc_now()),
            )

    # retention and deletion -------------------------------------------------------
    def purge_before(self, cutoff_ms: int) -> int:
        """Delete activity that ended before ``cutoff_ms``; returns the number of spans."""
        cur = self.conn.execute("DELETE FROM activity_span WHERE end_ms < ?", (cutoff_ms,))
        self.conn.execute("DELETE FROM system_event WHERE at_ms < ?", (cutoff_ms,))
        self.conn.execute("DELETE FROM auto_session WHERE end_ms < ?", (cutoff_ms,))
        self._forget_unused_apps()
        return cur.rowcount

    def delete_all(self) -> None:
        """Delete every recorded activity. Rules and exclusions are settings and stay."""
        for table in ("activity_span", "system_event", "auto_session", "browser_state"):
            self.conn.execute(f"DELETE FROM {table}")  # fixed table names, no user input
        self._forget_unused_apps()

    def _forget_unused_apps(self) -> None:
        self.conn.execute(
            "DELETE FROM app WHERE id NOT IN"
            " (SELECT app_id FROM activity_span WHERE app_id IS NOT NULL)"
        )
        self._app_ids.clear()

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

"""``browser_state`` table: the latest report per browser profile, gated by the user's consent."""

import sqlite3

from focuslab.browser.protocol import BrowserState
from focuslab.storage.repository import Repository

STALE_ROW_MS = 24 * 3600 * 1000


class BrowserStateStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._settings = Repository(conn)

    def collection_allowed(self) -> bool:
        """Browser consent, recording consent, and recording not paused by the user."""
        get = self._settings.get_setting
        return (
            get("consent.browser") == "1"
            and get("consent.recording") == "1"
            and get("activity.paused") != "1"
        )

    def apply(self, state: BrowserState, now_ms: int) -> bool:
        """Store ``state`` unless collection is off (then any old row is removed).

        Reports from one worker instance are applied in sequence order only, so a duplicate
        or late message can never overwrite a newer one.
        """
        if not self.collection_allowed():
            self.clear(state.browser, state.instance)
            return False
        self.conn.execute(
            "INSERT INTO browser_state (browser, instance, seq, focused, domain, updated_ms)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(browser, instance) DO UPDATE SET seq = excluded.seq,"
            " focused = excluded.focused, domain = excluded.domain,"
            " updated_ms = excluded.updated_ms WHERE excluded.seq > browser_state.seq",
            (state.browser, state.instance, state.seq, int(state.focused), state.domain, now_ms),
        )
        return True

    def clear(self, browser: str, instance: str) -> None:
        self.conn.execute(
            "DELETE FROM browser_state WHERE browser = ? AND instance = ?", (browser, instance)
        )

    def clear_all(self) -> None:
        self.conn.execute("DELETE FROM browser_state")

    def purge_stale(self, now_ms: int) -> None:
        self.conn.execute(
            "DELETE FROM browser_state WHERE updated_ms < ?", (now_ms - STALE_ROW_MS,)
        )

    def last_report_ms(self) -> int | None:
        row = self.conn.execute("SELECT MAX(updated_ms) FROM browser_state").fetchone()
        return row[0]

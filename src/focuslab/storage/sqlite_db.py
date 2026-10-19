"""SQLite connection with foreign keys, WAL and migrations applied."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from focuslab.storage.migrations import migrate


def connect(path: Path | str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open (creating if needed) the local database. ``":memory:"`` is allowed for tests."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), timeout=5, check_same_thread=check_same_thread, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Explicit transaction for an ``isolation_level=None`` connection."""
    conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")

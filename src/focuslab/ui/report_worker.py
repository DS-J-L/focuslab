"""Activity reports off the GUI thread.

``activity_report`` over a month takes seconds. It runs on one worker thread with its own
database connection, so it never holds ``SessionService.lock`` (the session tick and every
other page keep going) and the window stays responsive. Only finished results come back to
the GUI thread, through queued signals.

Requests are keyed (e.g. ``"day"``, ``"range"``): a newer request for a key supersedes an
older one, which is skipped if it has not started yet and dropped if it has.
"""

import logging
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from focuslab.activity.power import PowerSource
from focuslab.services.activity_service import activity_report
from focuslab.storage.sqlite_db import connect

log = logging.getLogger(__name__)


class _Worker(QObject):
    done = Signal(str, int, object)  # key, generation, (labeled, stats)
    error = Signal(str, int, str)

    def __init__(self, db_path: Path | str, latest: dict[str, int],
                 guard: threading.Lock, power: PowerSource | None) -> None:
        super().__init__()
        self._db_path = db_path
        self._power = power
        self._latest = latest
        self._guard = guard
        self.conn: sqlite3.Connection | None = None

    @Slot(str, int, object)
    def compute(self, key: str, generation: int, window: object) -> None:
        with self._guard:
            if self._latest.get(key) != generation:
                return  # superseded while queued
        try:
            if self.conn is None:
                # Closed from the GUI thread once this thread has finished.
                self.conn = connect(self._db_path, check_same_thread=False)
            start_ms, end_ms = window
            result = activity_report(self.conn, start_ms, end_ms, self._power)
        except Exception as exc:  # reported to the page; the next request retries
            log.warning("activity report failed: %s", exc)
            self.error.emit(key, generation, str(exc))
            return
        self.done.emit(key, generation, result)


class ActivityReporter(QObject):
    """Owned by the GUI thread. ``ready``/``failed`` carry the ``context`` given to
    ``request`` so the receiver knows which day or range the result is for."""

    _submit = Signal(str, int, object)
    ready = Signal(str, object, object)  # key, context, (labeled, stats)
    failed = Signal(str, object, str)  # key, context, message

    def __init__(
        self, db_path: Path | str, parent: QObject | None = None,
        power: PowerSource | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._power = power  # read on the worker thread only
        self._latest: dict[str, int] = {}
        self._guard = threading.Lock()
        self._contexts: dict[str, object] = {}
        self._generation = 0
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        self._thread = QThread()
        self._thread.setObjectName("focuslab-activity-report")
        self._worker = _Worker(self._db_path, self._latest, self._guard, self._power)
        self._worker.moveToThread(self._thread)
        self._submit.connect(self._worker.compute)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def request(self, key: str, start_ms: int, end_ms: int, context: object = None) -> None:
        self._ensure_thread()
        self._generation += 1
        with self._guard:
            self._latest[key] = self._generation
        self._contexts[key] = context
        self._submit.emit(key, self._generation, (start_ms, end_ms))

    def pending(self, key: str | None = None) -> bool:
        """Whether a result is still to come (for ``key``, or for any key)."""
        keys = [key] if key else list(self._contexts)
        return any(k in self._contexts for k in keys)

    def _take(self, key: str, generation: int) -> tuple[bool, object]:
        with self._guard:
            current = self._latest.get(key) == generation
        if not current or key not in self._contexts:
            return False, None
        return True, self._contexts.pop(key)

    @Slot(str, int, object)
    def _on_done(self, key: str, generation: int, result: object) -> None:
        current, context = self._take(key, generation)
        if current:
            self.ready.emit(key, context, result)

    @Slot(str, int, str)
    def _on_error(self, key: str, generation: int, message: str) -> None:
        current, context = self._take(key, generation)
        if current:
            self.failed.emit(key, context, message)

    def shutdown(self) -> None:
        """Let a running report finish, stop the thread and close its connection."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        with self._guard:
            self._latest.clear()  # queued requests are skipped
        self._contexts.clear()
        thread.quit()
        thread.wait()
        worker, self._worker = self._worker, None
        if worker and worker.conn is not None:
            worker.conn.close()

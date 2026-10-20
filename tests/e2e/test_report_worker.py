"""Activity statistics run on a worker thread with their own connection, never on the GUI
thread and never under ``SessionService.lock``."""

import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.activity.stats import local_day_bounds
from focuslab.ui import report_worker
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import ACTIVITY, MainWindow


@pytest.fixture
def window(qtbot, monkeypatch, daily_scenario, settle):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    ctx = AppContext(demo=True)
    daily_scenario(ctx.db_path, local_day_bounds(yesterday)[0] + 9 * 3_600_000)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.go(ACTIVITY)
    win.activity.show_day(yesterday)
    settle(win)
    yield win
    win.close_down()


class Calls(list):
    """Every report the worker computes: (thread id, connection, window)."""

    delay = 0.0


@pytest.fixture
def calls(monkeypatch):
    seen = Calls()
    real = report_worker.activity_report

    def spy(conn, start_ms, end_ms):
        seen.append((threading.get_ident(), conn, (start_ms, end_ms)))
        time.sleep(seen.delay)
        return real(conn, start_ms, end_ms)

    monkeypatch.setattr(report_worker, "activity_report", spy)
    return seen


def test_reports_use_a_worker_and_their_own_connection(window, calls, settle):
    window.activity.refresh()
    settle(window)
    assert calls
    assert {ident for ident, _, _ in calls} != {threading.get_ident()}
    assert all(conn is not window.ctx.service.repository.conn for _, conn, _ in calls)
    assert window.activity.cards["active"]._value.text() == "1시간 10분"


def test_reports_finish_while_the_session_lock_is_held(window, settle):
    """A long statistics query must never stall the session tick (which takes the lock)."""
    window._timer.stop()  # the 500 ms poll takes the lock on this thread; keep it out
    window._activity_timer.stop()
    held, release = threading.Event(), threading.Event()

    def hold():
        with window.ctx.service.lock:
            held.set()
            release.wait(20)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert held.wait(5)
        window.activity.range.setCurrentIndex(1)  # 30 days, computed while the lock is held
        settle(window)
        assert "기간 합계" in window.activity.range_summary.text()
        assert window.activity.loading.text() == ""
    finally:
        release.set()
        holder.join()


def test_the_window_stays_responsive_and_only_the_latest_day_is_computed(window, calls,
                                                                         settle):
    page = window.activity
    calls.clear()
    calls.delay = 0.8
    started = time.perf_counter()
    page.refresh()
    for _ in range(3):  # the user keeps stepping back while the first load is running
        page.show_day(page.day - timedelta(days=1))
    assert time.perf_counter() - started < 0.5  # nothing was computed on this thread
    assert page.loading.text() == "불러오는 중…"
    settle(window)
    assert page.loading.text() == ""
    skipped = [local_day_bounds(page.day + timedelta(days=n)) for n in (1, 2)]
    computed = [window_ for _, _, window_ in calls]
    assert local_day_bounds(page.day) in computed
    assert not any(bounds in computed for bounds in skipped)  # superseded while queued
    assert page.day_label.text().startswith(f"{page.day:%Y-%m-%d}")
    assert page.cards["total"]._value.text() == "0초"  # three days earlier: no data


def test_a_failed_report_is_shown_and_the_next_one_recovers(window, monkeypatch, settle):
    real = report_worker.activity_report

    def broken(conn, start_ms, end_ms):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(report_worker, "activity_report", broken)
    window.activity.refresh()
    settle(window)
    assert "불러오지 못했습니다" in window.activity.loading.text()
    monkeypatch.setattr(report_worker, "activity_report", real)
    window.activity.refresh()
    settle(window)
    assert window.activity.loading.text() == ""


def test_close_down_stops_the_worker_and_closes_its_connection(qtbot, settle):
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.go(ACTIVITY)
    settle(win)
    thread, worker = win.reporter._thread, win.reporter._worker
    assert thread is not None and thread.isRunning()
    win.close_down()
    assert thread.isFinished() and win.reporter._thread is None
    with pytest.raises(sqlite3.ProgrammingError):
        worker.conn.execute("SELECT 1")

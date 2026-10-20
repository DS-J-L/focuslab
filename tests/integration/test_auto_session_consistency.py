"""Automatic sessions are derived data: whatever was viewed, and in which order, the stored
sessions and the full export follow the timeline and the current rules."""

from datetime import datetime, timedelta

import pytest

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import ActivitySpan, Category, SpanKind
from focuslab.services.activity_service import ALL_TIME, activity_report, stored_auto_sessions
from focuslab.services.export_service import activity_dict
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect

MIN = 60_000


@pytest.fixture
def midnight(tmp_path):
    """20 minutes of coding from 23:50 to 00:10 across the last local midnight."""
    today = datetime.now().astimezone().date()
    midnight, _ = local_day_bounds(today)
    conn = connect(tmp_path / "m.db")
    ActivityRepository(conn).insert_span(
        ActivitySpan(midnight - 10 * MIN, midnight + 10 * MIN, SpanKind.ACTIVE, "code.exe")
    )
    yield conn, today, midnight
    conn.close()


def _stored(conn):
    return [(s.start_ms, s.end_ms, s.active_ms) for s in stored_auto_sessions(conn, *ALL_TIME)]


def _view(conn, first, days):
    start, _ = local_day_bounds(first)
    _, end = local_day_bounds(first + timedelta(days=days - 1))
    return activity_report(conn, start, end)[1]


@pytest.mark.parametrize("views", [
    [(-1, 2), (0, 1)],  # two days, then today
    [(0, 1), (-1, 1)],  # today, then yesterday
    [(0, 1), (-6, 7), (0, 1)],  # day -> week -> day
    [(-29, 30), (0, 1)],  # month -> day
])
def test_view_order_never_duplicates_a_session_crossing_midnight(midnight, views):
    conn, today, at = midnight
    for offset, days in views:
        _view(conn, today + timedelta(days=offset), days)
    assert _stored(conn) == [(at - 10 * MIN, at + 10 * MIN, 20 * MIN)]
    exported = activity_dict(Repository(conn))["automatic_sessions"]
    assert [s["active_ms"] for s in exported] == [20 * MIN]


def test_both_days_show_the_whole_session(midnight):
    conn, today, at = midnight
    for offset in (-1, 0):
        [session] = _view(conn, today + timedelta(days=offset), 1).sessions
        assert (session.start_ms, session.end_ms) == (at - 10 * MIN, at + 10 * MIN)


def test_export_is_current_without_opening_the_activity_page(midnight):
    conn, today, _ = midnight
    repo = Repository(conn)
    [session] = activity_dict(repo)["automatic_sessions"]  # nothing viewed yet
    assert session["category"] == Category.DEVELOPMENT.value

    _view(conn, today, 1)  # stored with the old rule
    ActivityRepository(conn).set_rule("app", "code.exe", Category.STUDY)
    [session] = activity_dict(repo)["automatic_sessions"]
    assert session["category"] == Category.STUDY.value

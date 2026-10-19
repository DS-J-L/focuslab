"""The acceptance scenario end to end: recorder -> browser bridge -> classifier -> automatic
sessions -> statistics, with no timer started and nothing typed in by the user."""

from datetime import datetime, timedelta

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import Category, ClassReason, SpanKind
from focuslab.services.activity_service import activity_report, stored_auto_sessions
from focuslab.storage.sqlite_db import connect

MIN = 60_000


def nine_am_today() -> tuple[int, int, int]:
    today = datetime.now().astimezone().date() - timedelta(days=1)  # a full past day
    day_start, day_end = local_day_bounds(today)
    return day_start, day_end, day_start + 9 * 60 * MIN


def test_a_day_is_recorded_classified_and_summarized_automatically(tmp_path, daily_scenario):
    day_start, day_end, t0 = nine_am_today()
    db = daily_scenario(tmp_path / "day.db", t0)
    conn = connect(db)
    labeled, stats = activity_report(conn, day_start, day_end)

    timeline = [((i.span.start_ms - t0) // MIN, (i.span.end_ms - t0) // MIN, i.span.kind,
                 i.span.exe_name, i.span.domain, i.label.category) for i in labeled]
    assert timeline == [
        (0, 30, SpanKind.ACTIVE, "code.exe", None, Category.DEVELOPMENT),
        (30, 40, SpanKind.ACTIVE, "chrome.exe", "github.com", Category.DEVELOPMENT),
        (40, 50, SpanKind.ACTIVE, "chrome.exe", "youtube.com", Category.UNKNOWN),
        (50, 60, SpanKind.IDLE, None, None, Category.BREAK),  # back-dated to the last input
        (60, 80, SpanKind.ACTIVE, "code.exe", None, Category.DEVELOPMENT),
    ]
    assert labeled[2].label.reason is ClassReason.AMBIGUOUS_SITE  # YouTube is not forced

    # totals add up and never exceed the elapsed time
    assert stats.total_ms == 80 * MIN and stats.active_ms == 70 * MIN
    assert stats.idle_ms == 10 * MIN and stats.locked_ms == 0
    assert sum(stats.by_category.values()) == stats.observed_ms == 80 * MIN
    assert sum(stats.by_app.values()) == stats.active_ms
    assert dict(stats.by_site) == {"github.com": 10 * MIN, "youtube.com": 10 * MIN}
    assert sum(stats.hourly_ms) == stats.active_ms
    assert stats.switches == 3 and stats.work_ms == 60 * MIN

    # automatic sessions without a timer: coding (incl. GitHub), the YouTube stretch,
    # the away time ends it, then coding again
    assert [(s.category, (s.start_ms - t0) // MIN, (s.end_ms - t0) // MIN)
            for s in stats.sessions] == [
        (Category.DEVELOPMENT, 0, 40), (Category.UNKNOWN, 40, 50), (Category.DEVELOPMENT, 60, 80),
    ]
    assert len(stored_auto_sessions(conn, day_start, day_end)) == 3
    conn.close()


def test_correcting_youtube_once_relabels_it_everywhere(tmp_path, daily_scenario):
    from focuslab.storage.activity_repository import ActivityRepository

    day_start, day_end, t0 = nine_am_today()
    conn = connect(daily_scenario(tmp_path / "day.db", t0))
    ActivityRepository(conn).set_rule("site", "youtube.com", Category.STUDY)
    labeled, stats = activity_report(conn, day_start, day_end)
    assert labeled[2].label.category is Category.STUDY
    assert stats.by_category[Category.STUDY] == 10 * MIN
    # study right after development is a different kind of work, still a separate session
    assert [s.category for s in stats.sessions] == [
        Category.DEVELOPMENT, Category.STUDY, Category.DEVELOPMENT,
    ]
    conn.close()


def test_spans_crossing_midnight_are_split_between_days(tmp_path, daily_scenario):
    day_start, day_end, _ = nine_am_today()
    t0 = day_end - 30 * MIN  # 23:30
    conn = connect(daily_scenario(tmp_path / "late.db", t0))
    _, first = activity_report(conn, day_start, day_end)
    _, second = activity_report(conn, day_end, day_end + 24 * 60 * MIN)
    assert first.observed_ms == 30 * MIN
    assert first.observed_ms + second.observed_ms == 80 * MIN
    conn.close()

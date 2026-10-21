"""Activity dashboard on the acceptance scenario: overview, timeline, tables, corrections."""

import sys
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import Category, ClassSource
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import ACTIVITY, SETTINGS, MainWindow


@pytest.fixture
def window(qtbot, monkeypatch, daily_scenario, settle):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    yesterday = datetime.now().astimezone().date() - timedelta(days=1)
    day_start, _ = local_day_bounds(yesterday)
    ctx = AppContext(demo=True)
    daily_scenario(ctx.db_path, day_start + 9 * 3_600_000)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    win.go(ACTIVITY)
    win.activity.show_day(yesterday)
    settle(win)
    yield win
    win.close_down()


def cell(table, row, col):
    return table.item(row, col).text()


def test_overview_timeline_and_tables(window):
    page = window.activity
    assert page.cards["total"]._value.text() == "1시간 20분"
    assert page.cards["active"]._value.text() == "1시간 10분"
    assert page.cards["idle"]._value.text() == "10분 0초"
    assert page.cards["switches"]._value.text() == "3회"
    assert page.cards["sessions"]._value.text() == "3개"
    assert len(page.timeline._bars) == 5
    assert page.top_sites.rowCount() == 2
    assert {cell(page.top_sites, r, 0) for r in range(2)} == {"github.com", "youtube.com"}
    assert page.spans.rowCount() == 5
    assert cell(page.spans, 2, 4) == "youtube.com" and cell(page.spans, 2, 5) == "미분류"
    assert "판단 보류" in cell(page.spans, 2, 7)
    assert cell(page.spans, 3, 3) == "유휴(입력 없음)"
    assert page.sessions.rowCount() == 3
    assert "기간 합계" in page.range_summary.text()


def test_correcting_a_site_always_creates_a_rule(window, settle):
    page = window.activity
    page.spans.selectRow(2)
    assert page.apply_button.isEnabled() and page.always.isEnabled()
    assert "youtube.com" in page.always.text()
    page.correct_to.setCurrentIndex(page.correct_to.findData(Category.STUDY))
    page.always.setChecked(True)
    page._apply_correction()
    settle(window)
    youtube = page._labeled[2]
    assert youtube.label.category is Category.STUDY and youtube.label.source is ClassSource.USER
    with window.ctx.activity_repo() as repo:
        assert repo.user_rules().sites == {"youtube.com": Category.STUDY}
    page.spans.selectRow(2)
    page._clear_correction()
    settle(window)
    youtube = page._labeled[2]
    assert youtube.label.source is ClassSource.USER_RULE  # the rule still applies
    window.go(SETTINGS)
    assert window.settings.rules.count() == 1


def test_idle_rows_cannot_be_corrected_and_timeline_selects_rows(window):
    page = window.activity
    page.spans.selectRow(3)
    assert not page.apply_button.isEnabled()
    page._timeline_clicked(page._labeled[4])
    assert page.spans.selectionModel().selectedRows()[0].row() == 4


def test_empty_day_and_navigation(window, settle):
    page = window.activity
    page.show_day(page.day - timedelta(days=3))
    settle(window)
    assert page.cards["total"]._value.text() == "0초"
    assert "기록이 없습니다" in page.category_legend.text()
    page.show_day(page.day + timedelta(days=30))  # never beyond today
    assert page.day == datetime.now().astimezone().date()


def test_page_does_not_depend_on_a_korean_system_locale(window, settle):
    import locale

    previous = locale.setlocale(locale.LC_ALL)
    locale.setlocale(locale.LC_ALL, "C")  # e.g. an English Windows (the CI runner)
    try:
        window.activity.refresh()
        settle(window)
        assert window.activity.timeline._ticks[0][1].endswith("시")
    finally:
        locale.setlocale(locale.LC_ALL, previous)


def test_auto_refresh_keeps_a_selection_and_skips_long_range_charts(window, monkeypatch,
                                                                    settle):
    page = window.activity
    calls = []
    monkeypatch.setattr(page, "refresh_statistics", lambda: calls.append("stats"))
    page.show_day(datetime.now().astimezone().date())
    settle(window)
    calls.clear()
    page.auto_refresh()
    assert calls == []  # charts over 7/30 days are not recomputed every 30 s
    page.show_day(page.day - timedelta(days=1))
    settle(window)
    page.spans.selectRow(0)
    page.auto_refresh()  # not today and a row is selected: nothing changes under the user
    assert page.spans.selectionModel().selectedRows()[0].row() == 0


def test_power_on_time_card_and_period_line(window):
    page = window.activity
    # Demo power: awake 08:30-18:30; the scenario records 1 h 20 m from 09:00.
    assert page.cards["power"]._value.text() == "10시간 0분"
    hint = page.cards["power"]._hint.text()
    assert "입력 기반 활성 1시간 10분(12%)" in hint and "FocusLab 기록 없음 8시간 40분" in hint
    assert not page.power_tip.isVisibleTo(window)  # ten idle minutes: nothing to suggest
    assert "PC 켜짐" in page.range_summary.text()


def test_sleep_tip_shows_one_line_with_a_settings_button(window):
    from focuslab.activity.power import PowerReport, PowerSettings

    page = window.activity
    hour = 3_600_000
    page.stats.power = PowerReport(
        10 * hour, 0, [(0, 2 * hour), (3 * hour, 4 * hour)], PowerSettings(0, 0)
    )
    page._fill_overview(page.stats)
    assert page.power_tip.isVisibleTo(window) and page.power_settings.isVisibleTo(window)
    text = page.power_tip.text()
    assert "2번(합계 3시간 0분)" in text and "'사용 안 함'" in text and "최대 2시간 0분" in text
    page.stats.power = None  # e.g. the event log no longer covers the day
    page._fill_overview(page.stats)
    assert page.cards["power"]._value.text() == "-"
    assert not page.power_tip.isVisibleTo(window)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event log")
def test_power_events_follow_recording_consent():
    ctx = AppContext()
    try:
        power = ctx.power_source()
        assert power.on_intervals(0, 1) is None  # no consent yet: the log is not read
        ctx.set_flag("consent.recording", True)
        assert ctx.power_source().enabled
        ctx.set_flag("consent.recording", False)
        ctx.stop_recording()  # what withdrawing consent in Settings does
        assert not power.enabled
    finally:
        ctx.service.shutdown()

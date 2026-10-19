"""Activity dashboard on the acceptance scenario: overview, timeline, tables, corrections."""

from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import Category, ClassSource
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import ACTIVITY, SETTINGS, MainWindow


@pytest.fixture
def window(qtbot, monkeypatch, daily_scenario):
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
    yield win
    ctx.service.shutdown()


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


def test_correcting_a_site_always_creates_a_rule(window):
    page = window.activity
    page.spans.selectRow(2)
    assert page.apply_button.isEnabled() and page.always.isEnabled()
    assert "youtube.com" in page.always.text()
    page.correct_to.setCurrentIndex(page.correct_to.findData(Category.STUDY))
    page.always.setChecked(True)
    page._apply_correction()
    youtube = page._labeled[2]
    assert youtube.label.category is Category.STUDY and youtube.label.source is ClassSource.USER
    with window.ctx.activity_repo() as repo:
        assert repo.user_rules().sites == {"youtube.com": Category.STUDY}
    page.spans.selectRow(2)
    page._clear_correction()
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


def test_empty_day_and_navigation(window):
    page = window.activity
    page.show_day(page.day - timedelta(days=3))
    assert page.cards["total"]._value.text() == "0초"
    assert "기록이 없습니다" in page.category_legend.text()
    page.show_day(page.day + timedelta(days=30))  # never beyond today
    assert page.day == datetime.now().astimezone().date()

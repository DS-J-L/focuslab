"""Home shows automatic recording next to manual sessions; pages and tray tell observing apart
from saving and keep a save failure visible until a save succeeds."""

import sqlite3
from datetime import datetime

import pytest
from PySide6.QtWidgets import QMessageBox

from focuslab.activity.recorder import ActivityRecorder, RecorderConfig
from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import ForegroundApp, ProbeSample
from focuslab.i18n import tr
from focuslab.ui.context import AppContext
from focuslab.ui.home_page import AUTO, MANUAL, TODAY
from focuslab.ui.main_window import ACTIVITY, HOME, MainWindow


@pytest.fixture
def no_dialogs(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.fixture
def home(qtbot, no_dialogs, daily_scenario, settle):
    """Only automatic recording today: no manual session was ever started."""
    ctx = AppContext(demo=True)
    today = datetime.now().astimezone().date()
    daily_scenario(ctx.db_path, local_day_bounds(today)[0] + 3_600_000)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    settle(win)
    yield win
    win.close_down()


def test_home_shows_todays_automatic_recording_without_any_manual_session(home):
    page = home.home
    assert page.card_active._value.text() == "1시간 10분"
    assert page.card_auto._value.text() == "3개"
    assert page.card_work._value.text() not in ("0초", "-")
    assert page.card_sessions._value.text() == "0" and page.card_on._value.text() == "0초"
    assert page.recording_status.text().startswith("자동 기록")


def test_every_home_card_says_whether_it_is_automatic_or_manual(home):
    page = home.home
    auto = (page.card_active, page.card_work, page.card_auto)
    manual = (page.card_sessions, page.card_on, page.card_off, page.card_cov)
    assert [c._tag.text() for c in auto] == [tr(AUTO)] * 3
    assert [c._tag.text() for c in manual] == [tr(MANUAL)] * 4
    assert all(c._tag.isVisibleTo(page) for c in auto + manual)


def test_home_summary_is_computed_on_the_worker_and_links_to_activity(home, settle):
    home.home.refresh()
    assert home.reporter.pending(TODAY)  # requested, not computed on the GUI thread
    settle(home)
    home.home.to_activity.click()
    assert home.stack.currentIndex() == ACTIVITY


def test_activity_metrics_name_how_they_are_measured(home, settle):
    home.go(ACTIVITY)
    settle(home)
    cards = home.activity.cards
    assert cards["active"]._title.text() == "입력 기준 활성 시간"
    assert cards["work"]._title.text() == "작업 카테고리 시간"
    note = home.activity.metrics_note.text()
    assert "작업 관련 추정 시간" in note and "다를 수 있습니다" in note
    assert "입력 기준 활성" in home.activity.range_summary.text()


class SteadyProbe:
    def sample(self) -> ProbeSample:
        return ProbeSample(ForegroundApp("code.exe", "Code"), 0.0)


@pytest.fixture
def recording(qtbot, no_dialogs, monkeypatch):
    """A real recorder (driven by hand) that saves on every tick."""
    ctx = AppContext(demo=True)
    ctx.set_flag("consent.recording", True)
    ctx.recorder = ActivityRecorder(ctx.db_path, SteadyProbe(), config=RecorderConfig(flush_s=0))
    ctx.recorder.start(run_thread=False)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.show()
    messages = []
    monkeypatch.setattr(win.tray, "showMessage", lambda *a: messages.append(a))
    win.messages = messages
    yield win
    win.close_down()


def test_a_save_failure_stays_visible_until_a_save_succeeds(recording, monkeypatch):
    win, rec = recording, recording.ctx.recorder
    page, tray = recording.activity, recording.tray
    rec.tick()
    win.go(ACTIVITY)
    win.poll()
    assert "● 관찰 중 · 저장 정상" in page.status.text()
    assert not page.save_warning.isVisibleTo(page)
    assert "저장 정상" in tray.health_action.text() and "저장 실패" not in tray.toolTip()

    repo = rec._repo
    update, insert = repo.update_span_end, repo.insert_span

    def broken(*args):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "update_span_end", broken)
    monkeypatch.setattr(repo, "insert_span", broken)
    rec.tick()
    win.poll()
    assert "● 관찰 중" in page.status.text() and "⚠ 저장 실패" in page.status.text()
    assert page.save_warning.isVisibleTo(page) and "disk I/O error" in page.save_warning.text()
    assert "저장 실패" in tray.health_action.text() and "저장 실패" in tray.toolTip()
    assert len(win.messages) == 1

    rec.tick()  # observing keeps working; that alone never clears the error
    win.poll()
    assert page.save_warning.isVisibleTo(page) and len(win.messages) == 1
    win.go(HOME)
    win.poll()
    assert "저장 실패" in win.home.recording_status.text()

    monkeypatch.setattr(repo, "update_span_end", update)
    monkeypatch.setattr(repo, "insert_span", insert)
    rec.tick()
    win.go(ACTIVITY)
    win.poll()
    assert "저장 정상" in page.status.text() and not page.save_warning.isVisibleTo(page)
    assert "저장 정상" in tray.health_action.text() and "저장 실패" not in tray.toolTip()

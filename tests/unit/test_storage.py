from datetime import UTC, datetime, timedelta

import pytest

from focuslab.domain.events import StateSegment
from focuslab.domain.models import (
    FocusState,
    SessionConfig,
    SessionMode,
    SessionStatus,
    StateSample,
)
from focuslab.storage.migrations import MIGRATIONS, current_version
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect

CONFIG = SessionConfig("알고리즘", SessionMode.CODING, 25, ("Code.exe", "chrome.exe"), True)


@pytest.fixture
def repo(tmp_path):
    conn = connect(tmp_path / "t.db")
    yield Repository(conn)
    conn.close()


def test_migrations_are_applied_once(tmp_path):
    path = tmp_path / "m.db"
    connect(path).close()
    conn = connect(path)
    assert current_version(conn) == MIGRATIONS[-1][0]
    assert conn.execute("SELECT COUNT(*) FROM migration").fetchone()[0] == len(MIGRATIONS)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_session_roundtrip(repo):
    sid = repo.create_session(CONFIG, "rules-test")
    rec = repo.get_session(sid)
    assert rec.goal == "알고리즘" and rec.mode is SessionMode.CODING
    assert rec.status is SessionStatus.RUNNING and rec.camera_enabled
    assert rec.allowed_apps == ("chrome.exe", "code.exe")


def test_samples_segments_and_feedback(repo):
    sid = repo.create_session(CONFIG, "r")
    repo.add_sample(sid, StateSample(0, FocusState.ON_TASK, 0.8, ("ALLOWED_APP",), "code.exe"))
    repo.add_sample(sid, StateSample(1, FocusState.POSSIBLY_OFF_TASK, 0.7, ("UNRELATED_APP",)))
    states = [s.state for s in repo.samples(sid)]
    assert states == [FocusState.ON_TASK, FocusState.POSSIBLY_OFF_TASK]
    assert repo.samples(sid)[0].reason_codes == ("ALLOWED_APP",)

    eid = repo.insert_segment(sid, StateSegment(1, 2, FocusState.POSSIBLY_OFF_TASK, ("X",)), "r")
    repo.extend_segment(eid, 5, ("game.exe",))
    repo.set_feedback(eid, FocusState.BREAK, "쉬는 중")
    repo.set_feedback(eid, FocusState.ON_TASK, "책 읽음")  # newer correction replaces older
    (seg,) = repo.segments(sid)
    assert (seg.start_s, seg.end_s, seg.app_names) == (1, 5, ("game.exe",))
    assert seg.corrected_label is FocusState.ON_TASK and seg.effective_state is FocusState.ON_TASK
    assert len(repo.feedback_rows(sid)) == 1
    repo.clear_feedback(eid)
    assert repo.segments(sid)[0].corrected_label is None


def test_delete_session_cascades(repo):
    sid = repo.create_session(CONFIG, "r")
    repo.add_sample(sid, StateSample(0, FocusState.ON_TASK, 1.0))
    eid = repo.insert_segment(sid, StateSegment(0, 1, FocusState.ON_TASK), "r")
    repo.set_feedback(eid, FocusState.BREAK)
    repo.delete_session(sid)
    for table in ("state_sample", "event", "feedback", "session_allowed_app"):
        assert repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_recover_interrupted_marks_crashed_sessions(repo):
    sid = repo.create_session(CONFIG, "r", started_at_utc="2026-10-20T01:00:00+00:00")
    for i in range(30):
        repo.add_sample(sid, StateSample(i, FocusState.ON_TASK, 1.0))
    done = repo.create_session(CONFIG, "r")
    repo.set_status(done, SessionStatus.FINISHED, "2026-10-20T02:00:00+00:00")
    assert repo.recover_interrupted() == [sid]
    rec = repo.get_session(sid)
    assert rec.status is SessionStatus.INTERRUPTED
    assert rec.ended_at_utc == "2026-10-20T01:00:30+00:00"
    assert len(repo.samples(sid)) == 30  # data is kept
    assert repo.recover_interrupted() == []


def test_purge_respects_retention(repo):
    now = datetime(2026, 10, 20, tzinfo=UTC)
    old = repo.create_session(CONFIG, "r", (now - timedelta(days=40)).isoformat())
    repo.set_status(old, SessionStatus.FINISHED)
    recent = repo.create_session(CONFIG, "r", (now - timedelta(days=2)).isoformat())
    repo.set_status(recent, SessionStatus.FINISHED)
    assert repo.purge_older_than(0, now) == 0
    assert repo.purge_older_than(30, now) == 1
    assert [s.id for s in repo.list_sessions()] == [recent]


def test_settings(repo):
    assert repo.get_setting("x", "d") == "d"
    repo.set_setting("x", "1")
    repo.set_setting("x", "2")
    assert repo.get_setting("x") == "2"
    repo.delete_setting("x")
    assert repo.get_setting("x") is None

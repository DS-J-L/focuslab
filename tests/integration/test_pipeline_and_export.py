"""Mock sensors -> fusion -> rules -> SQLite -> metrics/export, plus privacy regressions."""

import csv
import itertools
import json

import pytest

from focuslab.config import db_path
from focuslab.demo import DEMO_SESSIONS, seed_demo_sessions
from focuslab.domain.models import FocusState
from focuslab.services.export_service import (
    daily_totals,
    delete_all,
    export_csv,
    export_json,
    session_report,
)
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("seed") / "focuslab.db"
    ids = seed_demo_sessions(path)
    return path, ids


def test_demo_pipeline_produces_consistent_reports(seeded):
    path, ids = seeded
    repo = Repository(connect(path))
    assert len(ids) == len(DEMO_SESSIONS)
    for sid, spec in zip(ids, DEMO_SESSIONS, strict=True):
        report = session_report(repo, sid)
        minutes = spec[4]
        assert report.metrics.measured_s == minutes * 60
        assert sum(report.metrics.seconds.values()) == minutes * 60
        assert report.metrics.seconds[FocusState.BREAK] == 120
        # segments tile the session exactly
        assert report.segments[0].start_s == 0
        segs = report.segments
        assert all(a.end_s == b.start_s for a, b in itertools.pairwise(segs))
        assert report.segments[-1].end_s == minutes * 60
    corrected = [s for sid in ids for s in repo.segments(sid) if s.corrected_label]
    assert len(corrected) == 1
    days = daily_totals(repo, 7)
    assert len(days) == 7
    assert sum(sum(c.values()) for _, c in days) == sum(spec[4] * 60 for spec in DEMO_SESSIONS)


def test_camera_off_demo_session_never_reports_away(seeded):
    path, ids = seeded
    repo = Repository(connect(path))
    lecture = ids[1]
    assert not repo.get_session(lecture).camera_enabled
    states = {s.state for s in repo.samples(lecture)}
    assert FocusState.AWAY not in states


def test_export_json_and_csv(seeded, tmp_path):
    path, ids = seeded
    repo = Repository(connect(path))
    out = export_json(repo, tmp_path / "all.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["format"] == "focuslab-export" and len(data["sessions"]) == len(ids)
    first = data["sessions"][0]
    assert {"session", "metrics_after_corrections", "segments", "samples", "feedback"} <= set(first)
    assert "frame" not in out.read_text(encoding="utf-8")

    one = export_csv(repo, tmp_path / "one.csv", [ids[0]])
    with one.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == DEMO_SESSIONS[0][4] * 60
    assert set(rows[0]) == {
        "session_id", "started_at_utc", "goal", "mode", "second_offset", "state",
        "effective_state", "confidence", "reason_codes", "app_name",
    }


def test_effective_state_reflects_correction_in_export(seeded, tmp_path):
    path, ids = seeded
    repo = Repository(connect(path))
    out = export_json(repo, tmp_path / "c.json", [ids[2]])
    samples = json.loads(out.read_text(encoding="utf-8"))["sessions"][0]["samples"]
    changed = [s for s in samples if s["state"] != s["effective_state"]]
    assert changed and all(s["effective_state"] == "ON_TASK" for s in changed)


def test_only_the_database_is_written(tmp_path, monkeypatch):
    """No frames, images or video files are ever written to the data folder."""
    monkeypatch.setenv("FOCUSLAB_DATA_DIR", str(tmp_path / "data"))
    seed_demo_sessions(db_path())
    names = {p.name for p in (tmp_path / "data").iterdir()}
    assert names <= {"focuslab.db", "focuslab.db-wal", "focuslab.db-shm"}


def test_delete_all_removes_every_session(tmp_path):
    path = tmp_path / "d.db"
    seed_demo_sessions(path)
    repo = Repository(connect(path))
    repo.set_setting("consent.camera", "1")
    delete_all(repo)
    for table in ("session", "state_sample", "event", "feedback", "session_allowed_app"):
        assert repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert repo.get_setting("consent.camera") == "1"

"""Task relevance verification: evaluation data, recovery from model trouble, and privacy."""

import csv
import hashlib
import sqlite3
from pathlib import Path

import pytest

from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.relevance import model_manager
from focuslab.relevance.embedding import AnalyzerState, SemanticAnalyzer
from focuslab.relevance.engine import RelevanceEngine
from focuslab.relevance.models import RelevanceInput, RelevanceLevel
from focuslab.services.session_service import SessionService

DATA = Path(__file__).resolve().parents[1] / "data"
TITLE = "롤 챔피언스 결승 하이라이트"


def rows(name):
    with (DATA / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("name", ["relevance_eval.csv", "relevance_holdout.csv"])
def test_rules_never_contradict_the_evaluation_labels(name):
    """Rules alone may leave titles UNCERTAIN, but must never get one the wrong way round."""
    engine = RelevanceEngine()
    for row in rows(name):
        data = RelevanceInput(
            row["goal"], SessionMode.LECTURE, "chrome.exe", "youtube.com", row["title"]
        )
        level = engine.evaluate(data).level
        wrong = RelevanceLevel.POSSIBLY_UNRELATED if row["label"] == "related" else (
            RelevanceLevel.RELATED
        )
        assert level is not wrong, row


@pytest.fixture
def make(tmp_path, clock):
    created = []

    def build(script, name="s.db"):
        svc = SessionService(
            tmp_path / name,
            face_factory=lambda cfg: MockFaceSource(((10**6, "forward"),), clock),
            activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, script, loop=False),
            clock=clock,
            auto_tick=False,
        )
        created.append(svc)
        return svc

    yield build
    for svc in created:
        svc.shutdown()


def run(svc, clock, seconds):
    states = []
    for _ in range(seconds):
        clock.advance(1)
        states.append(svc.tick().state)
    return states


def test_a_study_session_flags_the_detour_and_little_else(make, clock):
    """Lecture -> notes -> lecture -> highlights -> lecture, second by second."""
    yt = ("chrome.exe", "active", "youtube.com")
    steps = [
        (300, (*yt, "Unity AR Foundation 기초 강의"), "on"),
        (120, ("notepad.exe", "active"), "on"),
        (120, (*yt, "ARCore 평면 인식 원리"), "on"),
        (180, (*yt, TITLE), "off"),
        (120, (*yt, "Vuforia 이미지 타겟 설정하기"), "on"),
    ]
    svc = make([(sec, *step) for sec, step, _ in steps])
    goal = "증강현실 프로그래밍 공부"
    svc.start(SessionConfig(goal, SessionMode.LECTURE, 0, ("chrome.exe",), True))
    states = run(svc, clock, sum(sec for sec, _, _ in steps))
    truth = [label for sec, _, label in steps for _ in range(sec)]
    pairs = list(zip(truth, states, strict=True))
    false_off = sum(t == "on" and s is FocusState.POSSIBLY_OFF_TASK for t, s in pairs)
    caught = sum(t == "off" and s is FocusState.POSSIBLY_OFF_TASK for t, s in pairs)
    assert false_off <= 2  # only the hysteresis seconds after returning to the lecture
    assert caught >= 180 - 61  # flagged after the 60 s grace period
    notes = states[300:420]
    assert notes.count(FocusState.ON_TASK) >= 115  # notes right after a lecture are work


# recovery --------------------------------------------------------------------------------


def test_a_corrupt_model_file_is_refused_and_the_rules_carry_on(tmp_path, monkeypatch):
    good, bad = b"model bytes", b"MODEL BYTES"  # same size, different content
    spec = model_manager.ModelFile(
        "m.onnx", "https://example.test/m", hashlib.sha256(good).hexdigest(), len(good)
    )
    monkeypatch.setattr(model_manager, "FILES", (spec,))
    (tmp_path / "m.onnx").write_bytes(bad)
    assert model_manager.installed_dir([tmp_path]) == tmp_path  # the size looks right ...
    with pytest.raises(ValueError, match="checksum"):  # ... but loading verifies it
        model_manager.verify(tmp_path)
    analyzer = SemanticAnalyzer(lambda: model_manager.load(tmp_path), "corrupt")
    engine = RelevanceEngine(analyzer)
    data = RelevanceInput(
        "증강현실 공부", SessionMode.LECTURE, "chrome.exe", "youtube.com", "오늘의 영상"
    )
    try:
        engine.evaluate(data)
        analyzer.wait_idle()
        assert analyzer.state == AnalyzerState.FAILED
        assert engine.evaluate(data).source == "RULE"
    finally:
        analyzer.close()


class SlowEmbedder:
    def embed(self, texts):
        import numpy as np

        return np.ones((len(texts), 4)) / 2


def test_turning_the_model_off_or_removing_it_mid_session_keeps_the_session_running(
    make, clock
):
    svc = make([(3600, "chrome.exe", "active", "youtube.com", "오늘의 영상")])
    svc.start(SessionConfig("증강현실 공부", SessionMode.LECTURE, 0, ("chrome.exe",), True))
    analyzer = SemanticAnalyzer(SlowEmbedder, "fake")
    svc.set_semantic(analyzer)
    run(svc, clock, 5)
    analyzer.wait_idle()
    run(svc, clock, 1)  # the answer is picked up on the tick after the worker finishes
    assert svc.snapshot().relevance.source == "EMBEDDING"
    svc.set_semantic(None)  # Settings: unticked, or "Remove model" (which unticks first)
    assert analyzer._closed
    states = run(svc, clock, 5)
    assert svc.snapshot().relevance.source == "RULE"
    assert FocusState.UNKNOWN not in states[-3:]  # estimates continue as before


# privacy ---------------------------------------------------------------------------------


def text_cells(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        cells = []
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                cells += [c for c in row if isinstance(c, str)]
        return cells
    finally:
        conn.close()


def test_page_titles_are_never_written_unless_the_user_keeps_a_rule(make, clock, tmp_path):
    svc = make([(3600, "chrome.exe", "active", "youtube.com", TITLE)])
    svc.start(SessionConfig("증강현실 공부", SessionMode.LECTURE, 0, ("chrome.exe",), True))
    run(svc, clock, 90)
    svc.answer_relevance(RelevanceLevel.POSSIBLY_UNRELATED)  # a one-time answer
    run(svc, clock, 5)
    assert not any(TITLE in cell for cell in text_cells(tmp_path / "s.db"))

    svc.answer_relevance(RelevanceLevel.POSSIBLY_UNRELATED, remember=True)
    assert any(TITLE in cell for cell in text_cells(tmp_path / "s.db"))
    svc.forget_page_titles()  # page-title consent withdrawn
    assert not any(TITLE in cell for cell in text_cells(tmp_path / "s.db"))

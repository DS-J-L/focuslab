"""Local embedding layer: never blocks, caches in memory, forgets titles, falls back to rules."""

import csv
import hashlib
import io
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from focuslab.domain.models import SessionMode
from focuslab.relevance import model_manager
from focuslab.relevance.embedding import LEISURE_AT, RELATED_AT, AnalyzerState, SemanticAnalyzer
from focuslab.relevance.engine import RelevanceEngine, semantic_result
from focuslab.relevance.models import RelevanceInput, RelevanceLevel, RelevanceReason

DATA = Path(__file__).resolve().parents[1] / "data"


class FakeEmbedder:
    """Axis 0 = the AR goal's topic, axis 1 = leisure; the rest is noise-free filler."""

    def __init__(self, gate: threading.Event | None = None) -> None:
        self.calls: list[str] = []
        self.gate = gate

    def embed(self, texts):
        out = []
        for text in texts:
            self.calls.append(text)
            if self.gate is not None:
                self.gate.wait(5)
            body = text.split(": ", 1)[1]
            if "증강현실" in body or "SLAM" in body:
                v = [1.0, 0.0, 0.3]
            elif "침착맨" in body or body in {"게임", "예능", "웃긴 영상"}:
                v = [0.0, 1.0, 0.3]
            else:
                v = [0.3, 0.3, 1.0]
            out.append(np.array(v) / np.linalg.norm(v))
        return np.array(out)


def analyzer(embedder=None, load=None):
    embedder = embedder or FakeEmbedder()
    return SemanticAnalyzer(load or (lambda: embedder), "fake-1"), embedder


def data(title, goal="증강현실 공부"):
    return RelevanceInput(goal, SessionMode.LECTURE, "chrome.exe", "youtube.com", title)


def test_lookup_answers_later_and_then_from_memory():
    a, emb = analyzer()
    try:
        assert a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초") is None  # queued, not computed
        assert a.wait_idle()
        margin = a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초")
        assert margin is not None and margin >= RELATED_AT
        calls = len(emb.calls)
        assert a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초") == margin
        assert len(emb.calls) == calls  # the same title is never analyzed again
        assert a.state == AnalyzerState.READY
    finally:
        a.close()


def test_engine_uses_the_model_only_where_rules_found_no_evidence():
    a, emb = analyzer()
    engine = RelevanceEngine(a)
    try:
        first = engine.evaluate(data("컴퓨터 비전 SLAM 기초"))
        assert first.source == "RULE"  # the tick is not held up by the model
        a.wait_idle()
        later = engine.evaluate(data("컴퓨터 비전 SLAM 기초"))
        assert later.level is RelevanceLevel.RELATED
        assert later.reasons == (RelevanceReason.TITLE_SIMILAR_TO_GOAL,)
        assert (later.source, later.model_version) == ("EMBEDDING", "fake-1")

        emb.calls.clear()
        decided = engine.evaluate(data("게임 플레이 모음"))  # rules already decided
        assert decided.level is RelevanceLevel.POSSIBLY_UNRELATED and decided.source == "RULE"
        assert engine.evaluate(data("YouTube")).reasons == (RelevanceReason.TITLE_UNINFORMATIVE,)
        a.wait_idle()
        assert emb.calls == []
    finally:
        a.close()


def test_a_title_closer_to_leisure_is_only_a_hint():
    a, _ = analyzer()
    engine = RelevanceEngine(a)
    try:
        engine.evaluate(data("침착맨 삼국지 정주행"))
        a.wait_idle()
        result = engine.evaluate(data("침착맨 삼국지 정주행"))
        assert result.level is RelevanceLevel.UNCERTAIN
        assert result.reasons == (RelevanceReason.TITLE_CLOSER_TO_LEISURE,)
        assert result.score <= LEISURE_AT
    finally:
        a.close()


def test_semantic_result_thresholds():
    assert semantic_result(RELATED_AT, "m").level is RelevanceLevel.RELATED
    assert semantic_result(RELATED_AT - 0.001, "m").reasons == (RelevanceReason.NO_EVIDENCE,)
    assert semantic_result(LEISURE_AT, "m").reasons == (RelevanceReason.TITLE_CLOSER_TO_LEISURE,)


def test_lookup_never_waits_for_a_slow_model_load():
    release = threading.Event()

    def slow_load():
        release.wait(5)
        return FakeEmbedder()

    a, _ = analyzer(load=slow_load)
    try:
        started = time.perf_counter()
        for _ in range(50):
            assert a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초") is None
        assert time.perf_counter() - started < 0.5
        assert a.state == AnalyzerState.LOADING
        release.set()
        assert a.wait_idle()
        assert a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초") is not None
    finally:
        release.set()
        a.close()


def test_forgetting_titles_discards_cached_and_in_flight_results():
    gate = threading.Event()
    a, emb = analyzer(FakeEmbedder(gate))
    try:
        a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초")
        deadline = time.time() + 5
        while not any("SLAM" in c for c in emb.calls) and time.time() < deadline:
            time.sleep(0.01)
        a.forget_titles()  # consent withdrawn while the model is working on this title
        gate.set()
        a.wait_idle()
        time.sleep(0.05)
        assert a.lookup("증강현실 공부", "컴퓨터 비전 SLAM 기초") is None
    finally:
        gate.set()
        a.close()


def test_a_model_that_cannot_load_leaves_the_rules_in_charge():
    def broken():
        raise OSError("model file is corrupt")

    a, _ = analyzer(load=broken)
    engine = RelevanceEngine(a)
    try:
        engine.evaluate(data("컴퓨터 비전 SLAM 기초"))
        a.wait_idle()
        assert a.state == AnalyzerState.FAILED and "corrupt" in a.error
        result = engine.evaluate(data("컴퓨터 비전 SLAM 기초"))
        assert result.source == "RULE" and result.level is RelevanceLevel.UNCERTAIN
    finally:
        a.close()


# model manager --------------------------------------------------------------------------


@pytest.fixture
def tiny_model(monkeypatch):
    """Replace the pinned files with two small ones served by a fake opener."""
    blobs = {"https://example.test/m.onnx": b"m" * 70_000, "https://example.test/t.model": b"t"}
    files = tuple(
        model_manager.ModelFile(name, url, hashlib.sha256(blob).hexdigest(), len(blob))
        for name, (url, blob) in zip(("m.onnx", "t.model"), blobs.items(), strict=True)
    )
    monkeypatch.setattr(model_manager, "FILES", files)
    monkeypatch.setattr(model_manager, "DOWNLOAD_BYTES", sum(f.size for f in files))
    opened = []

    def opener(url):
        opened.append(url)
        return io.BytesIO(blobs[url])

    return blobs, files, opener, opened


def test_install_verifies_reports_progress_and_skips_good_files(tmp_path, tiny_model):
    blobs, files, opener, opened = tiny_model
    progress = []
    folder = model_manager.install(tmp_path, lambda d, t: progress.append((d, t)), opener=opener)
    assert model_manager.installed_dir([folder]) == folder
    assert progress[-1] == (sum(map(len, blobs.values())),) * 2
    model_manager.install(tmp_path, opener=opener)
    assert len(opened) == 2  # already verified files are not downloaded again
    assert model_manager.remove([folder]) == 2
    assert model_manager.installed_dir([folder]) is None


def test_install_rejects_a_bad_checksum_and_leaves_nothing(tmp_path, tiny_model, monkeypatch):
    blobs, files, opener, _ = tiny_model
    blobs["https://example.test/m.onnx"] = b"x" * 70_000  # tampered download
    with pytest.raises(ValueError, match="checksum"):
        model_manager.install(tmp_path, opener=opener)
    assert list(tmp_path.iterdir()) == []


def test_install_can_be_cancelled(tmp_path, tiny_model):
    _, _, opener, _ = tiny_model
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(model_manager.InstallCancelled):
        model_manager.install(tmp_path, cancel=cancel, opener=opener)
    assert list(tmp_path.iterdir()) == []


def test_status_reports_a_missing_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(model_manager, "runtime_available", lambda: False)
    assert model_manager.status([tmp_path]) is model_manager.ModelStatus.RUNTIME_MISSING


# real model (only where it has been installed; CI runs without it) ------------------------

REAL = model_manager.installed_dir()


@pytest.mark.skipif(REAL is None, reason="relevance model not installed")
@pytest.mark.parametrize("name", ["relevance_eval.csv", "relevance_holdout.csv"])
def test_real_model_never_calls_a_related_title_unrelated_or_vice_versa(name):
    rows = list(csv.DictReader((DATA / name).open(encoding="utf-8")))
    a = SemanticAnalyzer(lambda: model_manager.load(REAL), model_manager.MODEL_VERSION)
    engine = RelevanceEngine(a)
    try:
        for row in rows:
            engine.evaluate(data(row["title"], row["goal"]))
            assert a.wait_idle(60)
        results = [(row, engine.evaluate(data(row["title"], row["goal"]))) for row in rows]
    finally:
        a.close()
    for row, result in results:
        if row["label"] == "related":
            assert result.level is not RelevanceLevel.POSSIBLY_UNRELATED, row
        else:
            assert result.level is not RelevanceLevel.RELATED, row
    related = [r for row, r in results if row["label"] == "related"]
    assert sum(r.level is RelevanceLevel.RELATED for r in related) >= len(related) * 0.6

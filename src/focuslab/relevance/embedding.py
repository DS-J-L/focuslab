"""Local semantic similarity between the session goal and page titles.

The model runs on the CPU in a background thread and never on the session tick or the UI
thread: ``SemanticAnalyzer.lookup`` answers from memory or returns None and queues the work.
Titles and their vectors live only in memory and are dropped when title consent ends.

Calibration (tests/data/relevance_eval.csv, checked on relevance_holdout.csv): raw cosine
similarity of short titles is compressed (related and unrelated overlap around 0.78-0.84),
so the score is a margin: similarity to the goal minus the highest similarity to a set of
leisure topics. The goal is encoded as an e5 "query", the title as a "passage".
"""

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# Margins from the calibration above (held-out: no unrelated title at or above RELATED_AT,
# no related title at or below LEISURE_AT). A low margin is only a hint, never a verdict.
RELATED_AT = 0.02
LEISURE_AT = -0.04
LEISURE_TOPICS = (
    "게임", "예능", "음악", "스포츠", "요리", "여행 브이로그", "쇼핑", "운동", "반려동물",
    "패션", "드라마 영화", "투자", "웃긴 영상", "자동차", "연애",
)
_MAX_TOKENS = 64
_PAD, _BOS, _EOS, _UNK = 1, 0, 2, 3  # XLM-R (fairseq) ids around the SentencePiece vocabulary
_GONE = object()


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """L2-normalized row vectors; texts carry their own "query: "/"passage: " prefix."""
        ...


class OnnxEmbedder:
    """multilingual-e5-small on onnxruntime's CPU provider, mean-pooled and normalized."""

    def __init__(self, folder: Path, threads: int = 1) -> None:
        import onnxruntime as ort
        import sentencepiece as spm

        from focuslab.relevance.model_manager import MODEL_FILE, TOKENIZER_FILE

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(folder / MODEL_FILE.name), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._spm = spm.SentencePieceProcessor(model_file=str(folder / TOKENIZER_FILE.name))

    def _ids(self, text: str) -> list[int]:
        # Same ids as the upstream XLM-R tokenizer: fairseq offset, SentencePiece <unk> -> 3.
        pieces = self._spm.encode(" ".join(text.split()))
        return [_BOS, *(p + 1 if p else _UNK for p in pieces[: _MAX_TOKENS - 2]), _EOS]

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        rows = [self._ids(t) for t in texts]
        width = max(len(r) for r in rows)
        ids = np.full((len(rows), width), _PAD, dtype=np.int64)
        mask = np.zeros_like(ids)
        for i, row in enumerate(rows):
            ids[i, : len(row)] = row
            mask[i, : len(row)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]
        pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
        return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


class AnalyzerState:
    IDLE = "IDLE"  # nothing requested yet; the model is loaded on first use
    LOADING = "LOADING"
    READY = "READY"
    FAILED = "FAILED"


class SemanticAnalyzer:
    """Goal-vs-title margins computed off the caller's thread, cached in memory (LRU)."""

    def __init__(
        self,
        load: Callable[[], Embedder],
        version: str,
        max_cache: int = 512,
    ) -> None:
        self.version = version
        self._load = load
        self._max_cache = max_cache
        self._lock = threading.Condition()
        self._cache: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._goals: dict[str, np.ndarray] = {}
        self._wanted: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._state = AnalyzerState.IDLE
        self._error: str | None = None
        self._closed = False
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    def lookup(self, goal: str, title: str) -> float | None:
        """The cached margin for (goal, title), or None after queueing it for the worker."""
        key = (goal, title)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            if self._closed or self._state == AnalyzerState.FAILED:
                return None
            self._wanted[key] = None
            self._wanted.move_to_end(key)
            while len(self._wanted) > 8:  # only recent pages matter; drop stale requests
                self._wanted.popitem(last=False)
            if self._thread is None:
                self._state = AnalyzerState.LOADING  # before the thread runs: no IDLE window
                self._thread = threading.Thread(
                    target=self._run, name="focuslab-relevance", daemon=True
                )
                self._thread.start()
            self._lock.notify()
        return None

    def forget_titles(self) -> None:
        with self._lock:
            self._cache.clear()
            self._wanted.clear()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cache.clear()
            self._wanted.clear()
            self._goals.clear()
            self._lock.notify()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Tests: block until every queued request has an answer (or failed)."""
        with self._lock:
            return self._lock.wait_for(
                lambda: not self._wanted or self._state == AnalyzerState.FAILED, timeout
            )

    def _run(self) -> None:
        try:
            embedder = self._load()
            leisure = embedder.embed([f"query: {t}" for t in LEISURE_TOPICS])
        except Exception as exc:  # missing runtime, corrupt file, out of memory
            log.warning("relevance model unavailable: %s", exc)
            with self._lock:
                self._state, self._error = AnalyzerState.FAILED, str(exc)
                self._wanted.clear()
                self._lock.notify_all()
            return
        with self._lock:
            self._state = AnalyzerState.READY
        failures = 0
        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._wanted or self._closed)
                if self._closed or self._state == AnalyzerState.FAILED:
                    return
                goal, title = next(reversed(self._wanted))  # newest page first
                goal_vector = self._goals.get(goal)
            try:
                if goal_vector is None:
                    goal_vector = embedder.embed([f"query: {goal}"])[0]
                title_vector = embedder.embed([f"passage: {title}"])[0]
                margin = float(goal_vector @ title_vector - (leisure @ title_vector).max())
            except Exception:
                log.warning("relevance inference failed", exc_info=True)
                margin = None
            with self._lock:
                # Dropped meanwhile (consent withdrawn, too old): the answer is not kept.
                still_wanted = self._wanted.pop((goal, title), _GONE) is not _GONE
                failures = 0 if margin is not None else failures + 1
                if failures >= 3:
                    self._state, self._error = AnalyzerState.FAILED, "inference failed"
                    self._wanted.clear()
                if margin is not None and still_wanted and not self._closed:
                    if len(self._goals) > 16:
                        self._goals.clear()
                    self._goals[goal] = goal_vector
                    self._cache[(goal, title)] = margin
                    while len(self._cache) > self._max_cache:
                        self._cache.popitem(last=False)
                self._lock.notify_all()

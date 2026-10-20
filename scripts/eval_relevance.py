"""Measure task-relevance accuracy, latency and memory on the evaluation sets.

    uv run python scripts/eval_relevance.py            # rules only, plus the model if installed

Reports, per set: how often a related title is called POSSIBLY_UNRELATED (the error that
matters most: a false off-task hint), how often an unrelated one is called RELATED, the
share left UNCERTAIN, and model load time, per-title latency and process memory.
"""

import csv
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from focuslab.domain.models import SessionMode  # noqa: E402
from focuslab.relevance import model_manager  # noqa: E402
from focuslab.relevance.embedding import SemanticAnalyzer  # noqa: E402
from focuslab.relevance.engine import RelevanceEngine  # noqa: E402
from focuslab.relevance.models import RelevanceInput, RelevanceLevel  # noqa: E402

SETS = ("relevance_eval.csv", "relevance_holdout.csv")


def rows(name: str) -> list[dict[str, str]]:
    with (ROOT / "tests" / "data" / name).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def judge(engine: RelevanceEngine, row: dict[str, str]):
    data = RelevanceInput(
        row["goal"], SessionMode.LECTURE, "chrome.exe", "youtube.com", row["title"]
    )
    return engine.evaluate(data)


def report(label: str, results: list[tuple[dict[str, str], RelevanceLevel]]) -> None:
    counts = Counter((row["label"], level) for row, level in results)
    related = sum(1 for row, _ in results if row["label"] == "related")
    unrelated = len(results) - related
    false_off = counts["related", RelevanceLevel.POSSIBLY_UNRELATED]
    false_on = counts["unrelated", RelevanceLevel.RELATED]
    uncertain = sum(n for (_, level), n in counts.items() if level is RelevanceLevel.UNCERTAIN)
    print(
        f"  {label:12} related→RELATED {counts['related', RelevanceLevel.RELATED]}/{related}"
        f" · unrelated→POSSIBLY_UNRELATED"
        f" {counts['unrelated', RelevanceLevel.POSSIBLY_UNRELATED]}/{unrelated}"
        f" · false off-task {false_off} · false related {false_on}"
        f" · uncertain {uncertain}/{len(results)} ({uncertain / len(results):.0%})"
    )


def main() -> int:
    process = psutil.Process()
    folder = model_manager.installed_dir()
    analyzer = None
    if folder:
        before = process.memory_info().rss
        started = time.perf_counter()
        embedder = model_manager.load(folder)
        load_s = time.perf_counter() - started
        analyzer = SemanticAnalyzer(lambda: embedder, model_manager.MODEL_VERSION)
        print(
            f"model {model_manager.MODEL_VERSION}: verify+load {load_s:.2f} s,"
            f" +{(process.memory_info().rss - before) / 2**20:.0f} MiB RSS"
        )
        latencies = []
        for row in rows(SETS[0])[:40]:
            started = time.perf_counter()
            embedder.embed([f"passage: {row['title']}"])
            latencies.append((time.perf_counter() - started) * 1000)
        latencies.sort()
        print(
            f"per-title inference: median {statistics.median(latencies):.1f} ms,"
            f" p95 {latencies[int(len(latencies) * 0.95) - 1]:.1f} ms (1 CPU thread)"
        )
    else:
        print("model not installed: rules only")
    for name in SETS:
        print(name)
        data = rows(name)
        rules_only = RelevanceEngine()
        report("rules", [(r, judge(rules_only, r).level) for r in data])
        if analyzer:
            engine = RelevanceEngine(analyzer)
            for r in data:
                judge(engine, r)
                analyzer.wait_idle(60)
            report("rules+model", [(r, judge(engine, r).level) for r in data])
    if analyzer:
        analyzer.close()
    print(f"process RSS {process.memory_info().rss / 2**20:.0f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

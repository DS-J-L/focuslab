"""Measure task-relevance accuracy, latency and memory on the evaluation sets.

    uv run python scripts/eval_relevance.py              # title sets (+ model if installed)
    uv run python scripts/eval_relevance.py --scenarios  # whole sessions, second by second
    uv run python scripts/eval_relevance.py --long-run 8 # hours of simulated ticks

Title sets: how often a related title is called POSSIBLY_UNRELATED (the error that matters
most: a false off-task hint), how often an unrelated one is called RELATED, the share left
UNCERTAIN, and model load time, per-title latency and process memory.

Scenarios: scripted sessions with a truth label per step, run through the real session
service (mock sensors, simulated clock) without relevance (the engine before PR-05), with
rules, and with rules + model. Reports seconds wrongly estimated POSSIBLY_OFF_TASK, how much
real deviation was estimated as such, and how long that took.

Long run: page changes every 30 s for N simulated hours with the model; reports CPU time,
memory growth and the analyzer cache size.
"""

import argparse
import csv
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from focuslab.config import DEFAULT_ALLOWED_APPS  # noqa: E402
from focuslab.domain.models import FocusState, SessionConfig, SessionMode  # noqa: E402
from focuslab.mock_sources import MockActivitySource, MockFaceSource  # noqa: E402
from focuslab.relevance import model_manager  # noqa: E402
from focuslab.relevance.embedding import SemanticAnalyzer  # noqa: E402
from focuslab.relevance.engine import RelevanceEngine  # noqa: E402
from focuslab.relevance.models import RelevanceInput, RelevanceLevel  # noqa: E402
from focuslab.services.session_service import SessionService  # noqa: E402

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


def load_analyzer() -> SemanticAnalyzer | None:
    folder = model_manager.installed_dir()
    if not folder:
        return None
    embedder = model_manager.load(folder)
    return SemanticAnalyzer(lambda: embedder, model_manager.MODEL_VERSION)


def title_sets() -> None:
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


# scenarios --------------------------------------------------------------------------------

LECTURE, CODING = SessionMode.LECTURE, SessionMode.CODING
YT = ("chrome.exe", "active", "youtube.com")
# name: (goal, mode, allowed apps, camera, [(seconds, activity step, truth "on" / "off")])
SCENARIOS = {
    "AR study: lecture, notes, LoL highlights": (
        "증강현실 프로그래밍 공부", LECTURE, ("chrome.exe",), True, [
            (600, (*YT, "Unity AR Foundation 기초 강의 3강 - YouTube"), "on"),
            (180, ("notepad.exe", "active"), "on"),
            (300, (*YT, "ARCore 평면 인식 원리"), "on"),
            (300, (*YT, "롤 챔피언스 결승 하이라이트"), "off"),
            (300, (*YT, "Vuforia 이미지 타겟 설정하기"), "on"),
        ],
    ),
    "DB exam: video, AI chat, notes, Netflix": (
        "데이터베이스 시험공부", LECTURE, ("chrome.exe",), True, [
            (480, (*YT, "SQL JOIN 실습"), "on"),
            (240, ("chrome.exe", "active", "chatgpt.com", "ChatGPT"), "on"),
            (360, ("chrome.exe", "active", "docs.google.com", "정규화 요약 - Google Docs"), "on"),
            (360, ("chrome.exe", "active", "netflix.com", "Netflix"), "off"),
            (240, (*YT, "트랜잭션과 동시성 제어"), "on"),
        ],
    ),
    "Coding: IDE, GitHub issues, music video": (
        "FocusLab 버그 수정", CODING, DEFAULT_ALLOWED_APPS[CODING], True, [
            (900, ("code.exe", "active"), "on"),
            (180, ("chrome.exe", "active", "github.com", "Issues · DS-J-L/focuslab"), "on"),
            (240, (*YT, "아이유 - 좋은 날 뮤직비디오"), "off"),
            (300, ("code.exe", "active"), "on"),
        ],
    ),
    "Korean history: lecture, unmarked entertainment": (
        "한국사 능력검정시험 공부", LECTURE, ("chrome.exe",), True, [
            (300, (*YT, "조선 후기 실학 사상"), "on"),
            (420, (*YT, "침착맨 삼국지 정주행"), "off"),
            (300, (*YT, "임진왜란 주요 전투"), "on"),
        ],
    ),
    "Passive lecture, camera off, no input": (
        "경제학 원론 복습", LECTURE, ("chrome.exe",), False, [
            (1200, ("chrome.exe", "idle", "youtube.com", "수요와 공급 곡선 강의"), "on"),
        ],
    ),
}


class _Clock:
    def __init__(self) -> None:
        self.ms = 1_000_000

    def monotonic_ms(self) -> int:
        return self.ms


def run_scenario(spec, mode: str, analyzer: SemanticAnalyzer | None, folder: Path):
    goal, session_mode, allowed, camera, steps = spec
    clock = _Clock()
    script = [(seconds, *step) for seconds, step, _ in steps]
    svc = SessionService(
        folder / f"{mode}.db",
        face_factory=lambda cfg: MockFaceSource(((10**6, "forward"),), clock),
        activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, script, loop=False),
        clock=clock,
        auto_tick=False,
    )
    if mode == "none":
        svc._judge_relevance = lambda *a: None  # the engine before PR-05
    if analyzer is not None:
        svc._relevance.semantic = analyzer
    svc.start(SessionConfig(goal, session_mode, 0, tuple(allowed), camera))
    truth = [label for seconds, _, label in steps for _ in range(seconds)]
    states = []
    for _ in truth:
        clock.ms += 1000
        states.append(svc.tick().state)
        if analyzer is not None:
            analyzer.wait_idle(30)
    svc._relevance.semantic = None  # the shared analyzer stays open for the next run
    svc.shutdown()
    return truth, states


def scenarios() -> None:
    analyzer = load_analyzer()
    modes = ["none", "rules"] + (["rules+model"] if analyzer else [])
    off = FocusState.POSSIBLY_OFF_TASK
    totals: Counter[tuple[str, str]] = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        for name, spec in SCENARIOS.items():
            print(name)
            for mode in modes:
                truth, states = run_scenario(
                    spec, mode, analyzer if mode == "rules+model" else None, Path(tmp)
                )
                pairs = list(zip(truth, states, strict=True))
                false_off = sum(t == "on" and s is off for t, s in pairs)
                real = sum(t == "off" for t, _ in pairs)
                caught = sum(t == "off" and s is off for t, s in pairs)
                on_s = sum(t == "on" for t, _ in pairs)
                on_ok = sum(t == "on" and s is FocusState.ON_TASK for t, s in pairs)
                delays, start = [], None
                for i, (t, s) in enumerate(pairs):
                    if t == "off" and (i == 0 or truth[i - 1] == "on"):
                        start = i
                    if start is not None and s is off:
                        delays.append(i - start)
                        start = None
                for key, value in (("false", false_off), ("on", on_s), ("ok", on_ok),
                                   ("caught", caught), ("real", real)):
                    totals[mode, key] += value
                delay = f"{delays[0]} s" if delays else "never" if real else "-"
                print(
                    f"  {mode:12} false off-task {false_off:4} s"
                    f" · deviation caught {caught:4}/{real} s (first after {delay})"
                    f" · on-task truth estimated ON_TASK {on_ok}/{on_s} s"
                )
    print("total")
    for mode in modes:
        print(
            f"  {mode:12} false off-task {totals[mode, 'false']}/{totals[mode, 'on']} s"
            f" · deviation caught {totals[mode, 'caught']}/{totals[mode, 'real']} s"
            f" · on-task truth estimated ON_TASK {totals[mode, 'ok']}/{totals[mode, 'on']} s"
        )
    if analyzer:
        analyzer.close()


def long_run(hours: float) -> None:
    analyzer = load_analyzer()
    if analyzer is None:
        print("model not installed: the long run needs it")
        return
    process = psutil.Process()
    titles = [r["title"] for name in SETS for r in rows(name)]
    titles += [f"{t} {i}" for i in range(4) for t in titles]  # 600 distinct pages
    engine = RelevanceEngine(analyzer)
    ticks = int(hours * 3600)
    rss0, cpu0, wall0 = process.memory_info().rss, sum(process.cpu_times()[:2]), time.time()
    peak = rss0
    for tick in range(ticks):
        title = titles[(tick // 30) % len(titles)]
        data = RelevanceInput(
            "증강현실 프로그래밍 공부", SessionMode.LECTURE, "chrome.exe", "youtube.com", title,
            idle_s=0.0,
        )
        engine.evaluate(data, 1_000_000 + tick * 1000)
        if tick % 30 == 0:
            analyzer.wait_idle(30)
            peak = max(peak, process.memory_info().rss)
    cpu = sum(process.cpu_times()[:2]) - cpu0
    pages = max(1, ticks // 30)
    print(
        f"{hours:g} simulated hours ({ticks} ticks, {pages} page changes) in"
        f" {time.time() - wall0:.0f} s wall: CPU {cpu:.1f} s"
        f" ({cpu / ticks * 1000:.2f} ms per tick, {cpu / pages * 1000:.1f} ms per page),"
        f" RSS {rss0 / 2**20:.0f} -> {process.memory_info().rss / 2**20:.0f} MiB"
        f" (peak {peak / 2**20:.0f}), cache {len(analyzer._cache)} entries"
    )
    analyzer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate task relevance.")
    parser.add_argument("--scenarios", action="store_true")
    parser.add_argument("--long-run", type=float, metavar="HOURS")
    args = parser.parse_args()
    if args.scenarios:
        scenarios()
    elif args.long_run:
        long_run(args.long_run)
    else:
        title_sets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

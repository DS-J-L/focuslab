"""Synthetic load for docs/performance.md (no OS access, throwaway database).

    uv run python scripts/bench_activity.py

1. Simulates a 24-hour recorder run (86,400 one-second ticks with app switches every ~40 s,
   idle periods and 10 s batch flushes) and reports memory before/after and database growth.
2. Fills 30 days x 1,500 spans and times the dashboard report for 1, 7 and 30 days.
"""

import gc
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from focuslab.activity.recorder import ActivityRecorder, RecorderConfig
from focuslab.activity.stats import local_day_bounds
from focuslab.domain.activity import ActivitySpan, ForegroundApp, ProbeSample, SpanKind
from focuslab.services.activity_service import activity_report
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.sqlite_db import connect

APPS = ["code.exe", "chrome.exe", "slack.exe", "winword.exe", "windowsterminal.exe"]


class SimClock:
    def __init__(self) -> None:
        self.ms = 0

    def monotonic_ms(self) -> int:
        return self.ms


def simulated_day(folder: Path) -> None:
    clock, proc = SimClock(), psutil.Process(os.getpid())
    start = int(time.time() * 1000) - 2 * 86_400_000
    state = {"i": 0}

    class Probe:
        def sample(self) -> ProbeSample:
            i = state["i"]
            idle = float(i % 3600 - 3000) if i % 3600 >= 3000 else 0.0  # 10 min idle per hour
            return ProbeSample(ForegroundApp(APPS[(i // 40) % len(APPS)]), max(0.0, idle))

    db = folder / "day.db"
    rec = ActivityRecorder(db, Probe(), clock=clock, wall=lambda: start + clock.ms,
                           config=RecorderConfig())
    rec.start(run_thread=False)
    gc.collect()
    rss0 = proc.memory_info().rss
    began = time.perf_counter()
    for i in range(86_400):
        state["i"] = i
        clock.ms += 1000
        rec.tick()
        if i == 3600:
            gc.collect()
            rss_hour = proc.memory_info().rss
    elapsed = time.perf_counter() - began
    rec.stop()
    gc.collect()
    rss1 = proc.memory_info().rss
    conn = connect(db)
    spans = conn.execute("SELECT COUNT(*) FROM activity_span").fetchone()[0]
    conn.close()
    print("## simulated 24 h recorder run")
    per_tick = elapsed / 86_400 * 1e6
    print(f"ticks: 86,400 in {elapsed:.1f}s ({per_tick:.0f} us per tick incl. flushes)")
    print(f"spans written: {spans}, database: {db.stat().st_size / 2**20:.2f} MiB")
    print(f"RSS: start {rss0 / 2**20:.1f} MiB, after 1 h {rss_hour / 2**20:.1f} MiB,"
          f" after 24 h {rss1 / 2**20:.1f} MiB")


def month_reports(folder: Path) -> None:
    db = folder / "month.db"
    conn = connect(db)
    activity = ActivityRepository(conn)
    today = datetime.now().astimezone().date()
    with activity.transaction():
        for d in range(30):
            t = local_day_bounds(today - timedelta(days=d))[0] + 8 * 3_600_000
            for i in range(1500):
                exe = APPS[i % len(APPS)]
                length = 20_000 + (i * 7919) % 40_000
                activity.insert_span(ActivitySpan(
                    t, t + length, SpanKind.ACTIVE, exe,
                    domain="github.com" if exe == "chrome.exe" else None,
                ))
                t += length
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    print("## dashboard reports on 45,000 spans")
    print(f"database: {db.stat().st_size / 2**20:.2f} MiB")
    _, end = local_day_bounds(today)
    for days in (1, 7, 30):
        start = local_day_bounds(today - timedelta(days=days - 1))[0]
        began = time.perf_counter()
        _, stats = activity_report(conn, start, end)
        print(f"{days:>2} day(s): {time.perf_counter() - began:.2f}s,"
              f" {len(stats.sessions)} automatic sessions")
    conn.close()


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="focuslab-bench-"))
    try:
        simulated_day(folder)
        month_reports(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()

"""Run the real recorder for a while against a throwaway database and report what it stored.

    uv run python scripts/activity_smoke.py --seconds 60 [--keep]

Prints spans (program names only), system events, and the recorder process' CPU time and
memory. Intended for Windows device checks and resource measurements; it records only into a
temporary folder that is deleted afterwards unless --keep is given.
"""

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import psutil

from focuslab.activity.probe import WindowsProbe
from focuslab.activity.recorder import ActivityRecorder, RecorderConfig
from focuslab.activity.win_events import WindowsEventThread
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.sqlite_db import connect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--idle", type=float, default=300, help="idle threshold in seconds")
    args = parser.parse_args()

    folder = Path(tempfile.mkdtemp(prefix="focuslab-smoke-"))
    db = folder / "smoke.db"
    proc = psutil.Process(os.getpid())
    rec = ActivityRecorder(
        db, WindowsProbe(), events=WindowsEventThread,
        config=RecorderConfig(idle_threshold_s=args.idle),
    )
    cpu0, t0 = proc.cpu_times(), time.monotonic()
    rec.start()
    time.sleep(1)
    hooked = rec.status().events_hooked
    session = bool(rec._events and rec._events.session_events)
    time.sleep(max(0.0, args.seconds - 1))
    rec.stop()
    cpu1, t1 = proc.cpu_times(), time.monotonic()

    conn = connect(db)
    repo = ActivityRepository(conn)
    spans = repo.spans_between(0, 2**62)
    events = repo.events_between(0, 2**62)
    conn.close()
    cpu = (cpu1.user + cpu1.system) - (cpu0.user + cpu0.system)
    print(f"foreground hook: {hooked}, session/power notifications: {session}")
    elapsed = t1 - t0
    print(f"elapsed {elapsed:.1f}s, CPU {cpu:.2f}s ({cpu / elapsed * 100:.2f}% of one core)")
    rss, size = proc.memory_info().rss / 2**20, db.stat().st_size / 1024
    print(f"RSS {rss:.1f} MiB, database {size:.0f} KiB")
    print(f"{len(spans)} spans, {len(events)} events: {[e['type'] for e in events]}")
    for s in spans:
        print(f"  {s.kind:<7} {s.duration_ms / 1000:7.1f}s  {s.exe_name}  ({s.display_name})")
    covered = sum(s.duration_ms for s in spans) / 1000
    print(f"covered {covered:.1f}s of {t1 - t0:.1f}s")
    if args.keep:
        print(f"kept {db}")
    else:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()

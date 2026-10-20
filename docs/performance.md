# Automatic activity recording: performance measurements

> Measured 2026-10-20 on one development PC: Windows 11 Pro 10.0.26200, Python 3.11.14 (uv).
> Reproduce with `uv run python scripts/activity_smoke.py --seconds 600` (real probe) and `uv run python scripts/bench_activity.py` (synthetic load).

## 1. Real-device background recording

| Run | Result |
| --- | --- |
| 10 minutes (`--seconds 600`) | CPU 0.12 seconds = **0.02% of one core**; RSS 31.4 MiB; DB 128 KiB; foreground hook and session/power notifications registered |
| 75 seconds, 30-second idle threshold | CPU 0.04%; RSS 31.2 MiB; active 36.2 seconds then idle 38.4 seconds, backdated to the last input |
| 45 seconds | CPU 0.07%; RSS 29.0 MiB |

The PC was unused throughout the ten-minute run; all 600 seconds formed one idle interval because there had already been no input for at least five minutes. This measures standby overhead and idle handling, not frequent switching. Switching load is covered by the synthetic run below.

Most RSS comes from Python, pywin32, and psutil. The recorder retains one open interval and bounded pending batches.

## 2. Simulated 24-hour run

Fake clock with the real recorder and SQLite: 86,400 one-second ticks, program switches about every 40 seconds, ten idle minutes per hour, and ten-second batch saves.

| Metric | Result |
| --- | --- |
| Processing per tick, including saves | About 12 microseconds |
| Recorded intervals | 1,992 |
| Database size | 0.36 MiB/day |
| Process RSS | 26.1 MiB initially; 26.1 MiB after one simulated hour; 26.0 MiB after 24 hours |

Closed intervals are discarded after the next successful batch. Save-failure queues are capped at 5,000 items. At 1,500-2,000 intervals/day, the estimated thirty-day database size is about 11 MiB.

## 3. Dashboard calculations

Synthetic 45,000 intervals: thirty days with 1,500 transitions/day. Calculations include classification, camera overlay, automatic-session rebuilding, and statistics.

| Range | Calculation time |
| --- | --- |
| One day | 0.07 seconds |
| Seven days | 0.35 seconds |
| Thirty days | 1.81 seconds |

The database was 3.71 MiB after a WAL checkpoint. The activity page refreshes today's data every thirty seconds; long-range charts refresh on date/range changes. Selecting an interval prevents periodic refresh from disrupting correction.

Reports now run on a worker with a separate SQLite connection; these original measurements are computation baselines, not a new measurement of the complete localized GUI. Regression check: `tests/integration/test_activity_privacy.py::test_a_month_of_activity_stays_fast` uses generous CI limits (one day under two seconds, thirty days under twenty seconds).

## 4. Persistence and durability

- WAL with `synchronous=NORMAL`; one transaction per ten-second batch updates the open interval and inserts closed intervals/events.
- After `TerminateProcess`, `PRAGMA integrity_check` returned `ok`; the last committed batch remained, with at most about ten seconds lost. Restart records `RECOVERED`. See `tests/integration/test_recorder_crash.py`.
- Sleep, logoff, and shutdown notifications trigger immediate saves.

## 5. Limitations

- One development PC only. Low-end laptops and several weeks of real use require further validation under PR-12.
- Camera inference load is part of manual focus sessions and is excluded from these measurements.

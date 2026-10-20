# FocusLab evaluation and improvement priorities

Evaluation date: 2026-10-20. Scope: the local working tree at the time of assessment, Windows/Python 3.11 development environment.

> Historical assessment: the defects below describe the evaluated revision, not a claim that every issue remains open. Subsequent consent/statistics fixes and UX changes address several findings. Preserve the reproductions as regression scenarios.

## Overall assessment

**A useful prototype, but consent withdrawal and statistics/export consistency need attention before general distribution.**

Goal-aware sessions, automatic recording, evidence, user corrections, and local storage are connected. Automatic recording and manual sessions still need a more cohesive product experience, and there are no published results against real user labels. Making existing records trustworthy has higher priority than adding sensors.

The assessment used source review, the existing activity screenshot, off-screen GUI tests, and synthetic-data reproductions. It did not include live camera capture, long-term use, installer validation, or external product comparison. Application implementation was not changed during the assessment.

## Strengths

- **Minimal collection and controls:** separate camera/automatic/browser choices and no saved raw video, window titles, or typed content. The evaluated revision nevertheless had the withdrawal defect below.
- **Evidence and correction:** reasons, unclassified labels, interval corrections, and app/site rules make mistakes understandable and correctable.
- **Explicit limits:** multi-purpose sites such as YouTube remain unclassified; head direction alone does not establish attention.
- **Architecture and testing:** separate UI/services/rules/storage, scripted sensors, migrations, recovery, and browser-protocol checks.
- **Recording cost:** hooks/polling, interval merging, and batched persistence; performance documentation describes both scope and limitations.

## Reproduced defects

### 1. P0: withdrawal does not stop an ongoing session's observations

Evidence: `_toggle_camera` / `_toggle_activity` in [settings_page.py](../src/focuslab/ui/settings_page.py), sensor factories in [context.py](../src/focuslab/ui/context.py), and `start` / `tick` in [session_service.py](../src/focuslab/services/session_service.py).

The evaluated settings actions changed consent flags only. The service retained its existing sources and did not recheck consent on each tick.

**Reproduction:** create a `demo=False` context with a fake camera and a tracked activity source, start a session, invoke both real settings withdrawal actions, and advance one tick. No actual camera/OS activity was read.

```text
consents_after_revoke = False False
camera_status_after_revoke = RUNNING
camera_stop_calls = 0
activity_sample_calls_after_revoke = 1
persisted_app_after_revoke = audit-app.exe
```

**Recommendation:** connect withdrawal to service stop operations. Release the camera and clear preview/latest observations. Replace the PC source with an unavailable source. Pause/resume must not re-enable withdrawn observation. Explain that background recording has separate consent.

**Acceptance:** withdrawal while running or paused stops relevant sensor calls and persistence, including after resume.

### 2. P1: changing the report range can duplicate stored automatic sessions

Evidence: `rebuild_auto_sessions` / `activity_report` in [activity_service.py](../src/focuslab/services/activity_service.py).

Detection clipped activity to the selected range, but replacement removed only sessions starting within the range. An existing session starting before the boundary survived while a clipped replacement was added.

**Reproduction:** one `code.exe` interval, ten minutes before midnight to ten minutes after it.

```text
Stored after two-day report: [23:50-00:10]
Stored after next-day report: [23:50-00:10, 00:00-00:10]
Original active time: 20 minutes
Sum of exported automatic-session active time: 30 minutes
```

This does not mean every on-screen activity total doubled; the defect affected stored derived sessions and complete JSON export.

**Recommendation:** define canonical detection independently of view ranges, then select overlapping sessions for display. If partial rebuilding is retained, define consistent replacement of sessions crossing range boundaries.

**Acceptance:** day/week/month query order does not change canonical sessions or exports for identical activity/rules, including across midnight.

### 3. P1: automatic sessions are absent from exports until Activity is opened

Evidence: `activity_dict` in [export_service.py](../src/focuslab/services/export_service.py) read only `stored_auto_sessions`, while rebuilding occurred in the report path.

**Reproduction:** insert twenty minutes of activity, then export before requesting a report: zero automatic sessions. Request the report and export again: one session. Rule changes could similarly leave stale exported summaries.

**Recommendation:** generate current results independently of page visits, or verify derived-data versions. Resolve alongside finding 2.

**Acceptance:** export immediately after recording, after visiting Activity, and immediately after correction all reflect current input/rules.

### 4. P1: cross-midnight manual sessions are attributed entirely to the start date

Evidence: `daily_totals` in [export_service.py](../src/focuslab/services/export_service.py) and `HomePage.refresh` in [home_page.py](../src/focuslab/ui/home_page.py).

Reports grouped every sample by its session's start date. Home selected sessions starting today.

**Reproduction:** one task-related sample at October 19 23:59:59 and another at October 20 00:00:00. Daily totals were two seconds on the 19th and zero on the 20th, instead of one each.

**Recommendation:** partition by each sample's actual `at_ms` in local time. Define legacy/missing-timestamp behavior. Separate Home's recent-session display limit from daily aggregation.

**Acceptance:** daily totals across midnight and pause/resume reconcile with overall totals.

### 5. P1: partial camera observation counts as full-interval coverage

Evidence: `compute_stats` in [stats.py](../src/focuslab/activity/stats.py), `CameraOverlay` in [camera_overlay.py](../src/focuslab/activity/camera_overlay.py), and the Activity work card.

Any camera coverage caused the entire activity interval's duration to be added to `camera_covered_ms`.

**Reproduction:** a ten-minute work interval with one second of camera observation reported 600 seconds of coverage.

**Recommendation:** calculate the intersection of actual observation intervals, activity intervals, and the query range. Preserve off/error/unavailable distinctions.

**Acceptance:** one observed second in ten minutes reports one second, including in partial-date/range views.

## Product and UX improvements

| Priority | Problem | Recommendation |
| --- | --- | --- |
| P1 | Automatic-only users see zero manual-session Home cards and may think recording is inactive | Combine recording health and today's activity with session start; identify each metric's source |
| P1 | Actual active use is input-based; lectures/reading may become idle. Work time is a fixed category sum | Use explicit input-based/category wording and explain differences from goal-aware session estimates |
| P1 | Reports ran on the GUI thread while holding the session-service lock; the original thirty-day benchmark was about 1.81 seconds | Use a worker with its own DB connection and verify navigation/stop controls and observation ticks remain responsive |
| P1 | Recorder errors existed internally but the page/tray could still appear healthy during save failures | Separate observing from saving; show last successful save and clear failures only after success |
| P2 | Activity stacks overview, timeline, rankings, interval/session tables, and long-range charts; sparse tables waste space | Prioritize overview/timeline, move detail/charts into collapsible sections or tabs, size tables by rows, show correction feedback |
| P2 | Numeric confidence values are hand-set rule weights, not validated accuracy | Explain that these are rule confidence or use levels; do not imply calibrated probabilities before field validation |
| P2 | Python/uv setup and unpacked browser-extension loading raise onboarding effort | After core fixes, provide an installer/uninstaller and browser-connection diagnostics; test a first-time user's complete flow |

## Recommended sequence

1. Fix withdrawal during running/paused sessions and add regression coverage.
2. Unify automatic-session persistence/export; fix midnight attribution and camera coverage.
3. Clarify Home/metric wording; add saving-health visibility and asynchronous reporting.
4. Validate coding, lectures, reading, meetings, multiple monitors, and absence against user labels. Report unknown share, false deviations, correction frequency, and return-time error.
5. Verify install, first record, browser connection, pause, export, deletion, and uninstall in a fresh Windows account.

Defer additional phone/emotion sensors until existing behavior is validated.

## Validation performed and limits

- `ruff check .`: passed.
- `node --test "browser_extension/test/*.test.js"`: eight passed.
- `python -m pytest -q --basetemp .pytest_audit_20261020 --tb=short`: **201 passed, two failed** because the restricted environment denied HKCU writes (`WinError 5`):
  - `test_autostart_entry_roundtrip_in_a_private_key`
  - `test_install_registers_both_browsers_and_binds_the_data_folder`
- The first pytest attempt could not use its default temporary folder. A workspace-local temporary directory produced the result above; pytest cache writes also warned. These environmental restrictions were not counted as product defects.
- The five findings were reproduced separately with in-memory SQLite and fake sensors. Passing existing tests did not cover those boundary cases.
- [Existing performance measurements](performance.md) were reviewed, not rerun as a new long-duration study.

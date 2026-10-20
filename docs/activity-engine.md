# Native Windows Activity Tracking Engine: analysis and design

> Baseline: `feat/v0.1-prototype` (`07bc83a`). Written 2026-10-20. PR-A-G are implemented; see [development plan section 18](../DEVELOPMENT_PLAN.md#18-v02-extension-native-windows-activity-tracking-engine).
>
> Goal: after explicit first-run consent, automatically record, classify, and analyze PC/browser activity without requiring timers or manual activity entry. Do not depend on ActivityWatch processes, APIs, databases, or watchers.

## 1. Baseline repository analysis (v0.1 prototype)

| Area | Existing implementation | Decision |
| --- | --- | --- |
| Architecture | `domain` contracts, `activity`/`camera` sensors, `focus` fusion/rules/metrics, SQLite `storage`, orchestration `services`, PySide6 `ui`; sensors publish observations only | Reuse these boundaries |
| Windows activity | `windows_tracker.py`: foreground HWND to PID/process, input-desktop lock detection, visible app selection; polled only by one-second session ticks; no window titles | Reuse helpers; add continuous recording, hooks, executable identity, access-denied and UWP handling |
| Idle detection | `idle_monitor.py`: `GetLastInputInfo` with `GetTickCount` wraparound | Reuse |
| Camera | Capture/inference workers, face presence, head pose, quality, calibration; manual sessions only | Reuse; no continuous capture. Eye-closure/phone detection remain unimplemented |
| Focus rules | TTL fusion, mode-aware rules, hysteresis, evidence, metrics | Reuse; suppress `BROWSER_DETAIL_UNKNOWN` when a domain is known |
| Manual sessions | Lifecycle, one-second samples/segments, unknown sleep gaps, interrupted-session recovery | Reuse; keep automatic sessions separate |
| SQLite | Versioned v1 migrations, WAL, foreign keys, repositories | Add v2+ migrations without losing existing records |
| Dashboard | Home, live session, seven-day reports/corrections, settings, shared cards/charts | Reuse/generalize widgets; add Activity |
| Tray/background | Close-to-tray during a session, single-instance `QLockFile` | Extend to continuous recording, pause/resume, immediate camera-off |
| Sign-in startup | None | Add HKCU `Run` entry |
| Browser extension | Planned only | Add MV3 and Native Messaging |
| Tests/CI | 93 baseline pytest tests, off-screen GUI, ruff, Windows CI, `uv build` | Extend and add Node extension tests |

Do not duplicate idle calculations, lock/process helpers, migration machinery, consent-dialog patterns, exports, widgets, the camera pipeline, or the rule engine.

## 2. Architecture

```text
Windows foreground/session/power/display events
    -> activity/win_events.py (message-only window thread)
    -> activity/recorder.py (event-triggered sampling + 1-second polling)
    -> ACTIVE / IDLE / LOCKED intervals, merging, gaps, clock-change handling
    -> 10-second batch flush -> activity_span / system_event (SQLite)

Chrome/Edge MV3 extension (active hostname)
    -> Native Messaging host -> browser_state (latest state per profile)
    -> recorder attaches domain to foreground browser intervals

activity/classifier.py -> category / confidence / evidence / source
activity/auto_sessions.py -> derived automatic sessions
activity/stats.py -> clipped daily/range totals without duplicate time
ui/report_worker.py -> reports on a worker with its own database connection
ui/activity_page.py -> activity dashboard; home/tray -> recording health

Existing SessionService -> manual-session samples and optional camera -> state_sample
```

### Time accounting and duplicate prevention

- `activity_span` is the single nonoverlapping timeline. A moment is active (app/domain), idle, or locked. Sleep, app-not-running, and paused-recording periods have no rows and are not counted as use.
- A domain is an attribute of an active interval while a browser is foreground, not a parallel source of elapsed time. Background tabs/unfocused windows are excluded; program and site totals remain consistent.
- Automatic sessions group intervals; their durations are not added to timeline totals. Manual-session overlap is marked with `manual_session_id`.
- Detect automatic sessions over complete runs between long breaks (five-minute gaps/idle/lock by default), independently of the selected view range. Cross-midnight sessions are stored once; views show overlapping sessions. Complete exports recalculate from current activity and rules rather than trusting a view-dependent cache.
- Total PC use is active + idle; locked time is separate. Input-based active time is active. Watching/reading without input becomes idle past the threshold. Work-category time adds active development/study/documentation/research/productivity time. Manual-session task-related estimates also use the goal, allowed apps, and camera and are a different metric.
- Recorder health separates probe errors from database-save errors. A save error clears only on a successful save. Expose the last successful save and the start of consecutive failures.
- Store UTC epoch milliseconds; advance interval duration with a monotonic clock. If wall time differs by more than five seconds, close the interval, start at the new timestamp, and record `CLOCK_CHANGED`.
- Abnormally long polling gaps close the interval at the last observation and leave an unobserved gap.

### Idle handling

When `GetLastInputInfo` exceeds the configurable threshold (five minutes by default), close the active interval and start idle time **backdated to the last input**. On input, close idle and start a new active interval, recording the return time. Do not read keys, typed content, or coordinates.

## 3. Data model (migrations v2-v5)

Use the repository's singular-table convention and separate feedback records.

| Concept | Implementation | Content |
| --- | --- | --- |
| Window/idle activities | `activity_span`, `kind=ACTIVE/IDLE/LOCKED` | Nonoverlapping intervals, app, domain, classification |
| Browser activities | `activity_span.domain` + `browser_state` | Interval hostname and latest extension state |
| Activity events | `system_event` | Start/stop/pause, lock, sleep, logoff, clock changes, recovery |
| Program identity | `app` | Lowercase executable name as stable ID; display name |
| Activity categories | `Category` enum | Ten fixed categories |
| Classification rules | `classification_rule` | User app/domain rules; built-ins stay in code |
| User corrections | `activity_feedback` | One category correction per interval |
| Automatic sessions | `auto_session` | Recalculable derived data |

## 4. Privacy defaults

- Store executable/product names, active hostname, interval timestamps, and classification. Do not store window titles, full executable paths, full URLs/paths/search terms/page contents, typed content, mouse coordinates, screenshots, or camera footage.
- Inspect executable paths only in memory for game-library hints, then discard them.
- PC recording, browser recording, and camera observation require separate consent. Do not query the OS or store browser state before consent or while recording is paused.
- Exclusions leave only unnamed Excluded time in the automatic timeline.

## 5. Work packages

| Package | Branch | Scope |
| --- | --- | --- |
| PR-A | `feat/activity-collector` | Design, schema v2, Win32 identity/access/UWP probes, recorder/merging/batches, foreground hooks, app integration |
| PR-B | `feat/idle-system-events` | Backdated idle, lock/sleep/logoff/display events, clock changes, recovery, startup, persistent tray, pause, onboarding |
| PR-C | `feat/browser-tracker` | Chrome/Edge MV3, Native Messaging host, registration/removal, sender/input checks, deduplication, domain intervals |
| PR-D | `feat/activity-classifier` | Categories/rules, confidence/evidence/source, corrections becoming rules, exclusions |
| PR-E | `feat/auto-sessions` | Detection/persistence and manual-session/rule/camera integration |
| PR-F | `feat/activity-dashboard` | Daily overview/timeline, daily/weekly/monthly/hourly/switch/return statistics |
| PR-G | `chore/activity-stability-release` | Retention/export/deletion, benchmarks, long runs, privacy/docs/CI |

These were developed as stacked branches and merged in sequence. Check each PR's base: merging into another feature branch alone does not integrate it into `main`. The final integration must reach `main`.

## 6. Implementation summary

- The planned boundaries are implemented. Individual PR descriptions and [performance measurements](performance.md) contain validation results.
- Instead of a named pipe/local socket, each native host writes its profile's latest state to the same SQLite database and the recorder reads it. No port is opened; startup order is independent; user-folder permissions protect the file; repeated state is idempotent.
- Camera overlays apply only during manual focus sessions, preserving the prohibition on continuous camera observation.
- UI language is separate from stable state/category/evidence codes. English message IDs and a Korean catalog localize labels without altering stored activity.

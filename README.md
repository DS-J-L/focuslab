# FocusLab

**Know your workflow, not just your screen time.**

FocusLab is a local-first, open-source Windows desktop app for reviewing work patterns during study and development. It combines your session goal, PC activity, and optional webcam observations to distinguish estimated task-related activity, possible task deviation, time away, and insufficient evidence.

> **Status: v0.1 developer prototype with an automatic activity recording engine.** The PySide6 app includes optional face/head-pose observation, mode-aware rules, live sessions, reports, and corrections. With consent, it also records and classifies PC/browser activity in the background and detects automatic sessions. ActivityWatch is not required. Thresholds and classification rules are hypotheses pending field validation (PR-12); a distributable installer (PR-13) is not available yet. See the [engine design](docs/activity-engine.md).

## Product principles

- **Goal and context:** coding, lectures, reading/writing, and custom modes have different allowed apps and expectations.
- **Explainable observations:** see the evidence behind an estimate and correct it yourself.
- **Explicit uncertainty:** looking away or covering the camera does not establish that you are off task.
- **Local processing:** no account or cloud service is required. Background activity recording requires consent; the camera runs only in sessions you start.
- **Minimal collection:** no saved camera footage, audio, screenshots, typed content, or sensitive window titles.

FocusLab does not directly measure attention and does not diagnose or treat ADHD. Its states are estimates of observable behavior, not guarantees of learning outcomes or medical judgments.

## Run from source

The supported development target is **Windows 11 x64 / Python 3.11 / uv**. Windows 10 compatibility requires separate testing and is not officially promised. Install uv using the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
git clone https://github.com/DS-J-L/focuslab.git
cd focuslab
uv sync --locked
uv run focuslab --fetch-models   # Optional: download and verify the 3.7 MB face model
uv run focuslab
```

| Command | Behavior |
| --- | --- |
| `uv run focuslab` | Open the app. First-run automatic recording is opt-in; PC observation and camera consent are handled separately. |
| `uv run focuslab --background` | Start in the tray, as used by the sign-in startup entry. Exit quietly if already running. |
| `uv run focuslab --demo` | Use scripted sensors without reading the real camera or PC activity. |
| `uv run focuslab --language en` | Use English for this run. Use `ko` for Korean. |
| `uv run focuslab --seed-demo` | Add four synthetic sessions to the local database for exploring reports. |
| `uv run focuslab --check` | Print versions, paths, model checksum, startup/bridge status, and dependency availability. |
| `uv run focuslab --fetch-models` | Download the face model from the official MediaPipe repository and verify its SHA256. |
| `--data-dir <folder>` | Override the default `%LOCALAPPDATA%\FocusLab` data folder. |

Without a face model or camera, sessions can continue using PC observations. The model download is the only network operation performed by the app.

### Interface language

The app supports **English and Korean**. English is the default; the first-run setup lets you pick the language, and it applies right away. Later, choose **Settings > Appearance > Language** to save a preference, then restart FocusLab to apply it. A language change does not interrupt your current session or translate your saved goals, app names, or records.

`--language en|ko` or `FOCUSLAB_LANGUAGE=en|ko` overrides the saved preference for a run. Repository documentation is maintained in English. See the [translation guide](docs/internationalization.md).

### Optional browser site recording (Chrome / Edge)

1. In Settings > Browser site recording, choose **Install in Chrome** or **Install in Edge**. This asks for consent if needed and registers the Native Messaging host in HKCU without administrator rights.
2. Once the extension is listed in the Chrome Web Store or Edge Add-ons, the button opens that page; choose **Add**. Until then, the button copies the extension to `%LOCALAPPDATA%\FocusLab\browser-extension`, opens it in Explorer, opens a browser window, and copies `chrome://extensions` (or `edge://extensions`) to the clipboard. Browsers do not let other programs open that page directly. Paste the address, turn on Developer mode, and drag the folder onto the page.
3. While the browser is in front, the extension reports only the active tab's hostname. Program recording works without the extension.

To publish the extension to the stores, see [Publishing the browser extension](docs/browser-extension-store.md).

```powershell
uv run ruff check .
uv run pytest                                   # Unit, integration, and off-screen GUI tests
node --test "browser_extension/test/*.test.js"  # Extension tests
uv build
uv run python scripts/activity_smoke.py --seconds 60   # Real Win32 probe, temporary database
uv run python scripts/bench_activity.py                # Synthetic load and performance
```

### Build FocusLab.exe

```powershell
uv run --group build python scripts/build_exe.py
```

This creates `dist\FocusLab\FocusLab.exe` (no console window, about 340 MB folder). Keep or copy the whole `dist\FocusLab` folder: the exe needs the `_internal` folder next to it. The face model is bundled when `assets\models\face_landmarker.task` exists. The exe accepts the same options as `uv run focuslab`; console output such as `--check` appears only when piped (`.\FocusLab.exe --check | more`). **Start at sign-in** and **Install connection** register the exe's own path, so turn them off and on again after moving the folder. Load the browser extension from `dist\FocusLab\_internal\browser_extension` (Settings > Open extension folder).

GitHub Actions checks lint, tests, the diagnostic CLI, and package builds on a Windows runner. Camera hardware, permissions, and long-running GUI behavior require separate Windows testing.

## Implemented prototype features

- **Automatic activity recording:** consent-based recording without a timer. Foreground executable/product names are observed with `SetWinEventHook` plus one-second polling. Idle time (five minutes by default, backdated to last input), lock, sleep, logoff, user switching, and display-off events are handled. Sleep/unobserved time is not counted. Batch persistence limits abrupt-process-exit loss to about ten seconds. Tray recording, pause/resume, and optional sign-in startup are supported.
- **Optional browser sites:** Chrome/Edge MV3 extension with Native Messaging; background tabs and private windows are excluded.
- **Automatic classification:** development, study, documentation, research, communication, entertainment, gaming, productivity tools, break/inactive, and unclassified. Labels include confidence, evidence, and source. Ambiguous sites such as YouTube stay unclassified unless you choose a rule. App/site exclusions are supported.
- **Automatic sessions:** group activity by absence and sustained work-category changes, and calculate detours/return times. Overlapping manual sessions are marked without adding duplicate activity time. Detection is independent of the selected report range; exports recalculate from current activity and rules.
- **Activity:** daily overview, category/program/site totals, timeline, interval correction, automatic sessions, and 7/30-day statistics. Long-range reports run on a worker with its own database connection. Saving failures and last successful save times are visible.
- **Home:** automatic recording status and daily activity summary alongside manual focus-session metrics; goal, mode, target time, allowed apps (including selection from open apps), and optional camera controls.
- **Live session:** one-second estimates and evidence, confidence, foreground app, last input, head pose, in-memory preview with optional landmarks, timeline, pause, break, immediate correction, and finish. Closing the window can continue recording in the tray.
- **Reports:** seven-day state totals, per-session task-related share, possible deviations, return times, app switches, longest streak, coverage, interval evidence/corrections, goal-achievement self-report, JSON/CSV export, and deletion. Daily totals use actual observation timestamps.
- **Settings:** separate consent controls, language, data location, retention, complete export/deletion, browser setup, camera device, model download, four-step calibration, and rule explanations. Withdrawing camera/PC observation consent also stops that observation in an ongoing session.
- **Recovery:** uncleanly ended sessions are marked interrupted on restart. Observation gaps become `UNKNOWN`.

## How estimates work

Sensors publish observations; the mode-aware [rule engine](src/focuslab/focus/rules.py) combines them over time and returns states with evidence codes.

- A non-allowed app for at least 15 seconds produces `POSSIBLY_OFF_TASK`; brief switches retain the previous state.
- An absent face for 20 seconds (60 in reading/writing) plus at least 20 seconds without input can produce `AWAY`.
- Looking away for 15 seconds (30 in reading/writing) plus ten seconds without input can produce `POSSIBLY_OFF_TASK`. **Looking down alone does not trigger this estimate.**
- Camera off, occlusion, darkness, errors, and stale observations are missing evidence. Face observations expire after two seconds and PC observations after three; camera loss alone does not establish deviation or absence.
- Entering task-related/unknown states requires three seconds of sustained evidence to prevent flicker. A user-requested break is immediate.
- Without browser details, the app explains that browser activity is unknown. Allowed-app lists can include sites such as `github.com`.

Automatic recording uses input-based idle detection, so reading or watching a lecture without input may count as idle. Work-category totals are category sums; manual-session estimates also consider your goal and allowed apps. These are different measurements, and the UI explains the distinction.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/focuslab/` | Entry point, paths/defaults, localization, demo sensors/data, model download |
| `domain/` | States, observations, sessions, segments, and sensor/clock contracts |
| `camera/` | Capture, face landmarks, head pose, and calibration |
| `activity/` | Win32 probes/hooks, recorder, classifier, automatic sessions, camera overlays, statistics |
| `browser/`, `browser_extension/` | Native Messaging host/protocol, Chrome/Edge registration, MV3 extension and JS tests |
| `focus/` | Sensor fusion, mode-aware rules, evidence, and metrics |
| `storage/` | SQLite, migrations, and repositories |
| `services/` | Session/worker orchestration, activity reporting, export/deletion |
| `ui/` | Window, pages, dialogs, tray, shared widgets, background report worker |
| `locales/` | Korean translations of English application messages |
| `scripts/` | Real-device smoke checks and synthetic benchmarks |
| `assets/models/` | Optional face model downloaded with `--fetch-models`; not committed |
| `tests/unit/`, `tests/integration/`, `tests/e2e/` | Unit, pipeline/persistence, and off-screen GUI tests |
| `.github/` | Windows CI, issue forms, and PR template |

Paths below `src/focuslab/` in the table are relative to that package unless otherwise indicated.

## Observation states

| State | Meaning |
| --- | --- |
| `ON_TASK` | Estimated activity related to the configured task |
| `POSSIBLY_OFF_TASK` | Possible task deviation |
| `AWAY` | Estimated time away |
| `BREAK` | A break explicitly requested by the user |
| `UNKNOWN` | Missing, insufficient, or unreliable evidence |

Camera-free sessions are not penalized. Unknown, break, and away time are reported separately. The optional Chrome/Edge extension provides hostname information that the desktop process alone cannot obtain reliably.

## Development roadmap

Roadmap labels such as PR-09 are work-package names, not necessarily GitHub pull-request numbers.

| Stage | Scope | Status |
| --- | --- | --- |
| PR-00 | Repository, policies, environment, mock sensors, basic PySide6 window | Prototype implemented |
| PR-01-02 | Session lifecycle, SQLite, camera | Prototype implemented |
| PR-03-06 | Face/head pose, Windows activity, state engine | Prototype implemented; thresholds remain hypotheses |
| PR-07-08 | Dashboard, reports, export/deletion, v0.1 MVP | Prototype implemented; extended soak and cross-PC validation remain |
| PR-A-G | Native activity collection, idle/system events, browser extension, classification, automatic sessions, dashboard, stability | Implemented; see [plan section 18](DEVELOPMENT_PLAN.md#18-v02-extension-native-windows-activity-tracking-engine) |
| PR-10-11 | Optional phone detection, personalization, quiet coaching | Planned |
| PR-12-13 | Field validation, performance/packaging, Windows installer | Planned |

The [development plan](DEVELOPMENT_PLAN.md) defines scope and completion criteria. Implement changes on feature branches, target `main` when integrating them, validate, and review before merging. `FocusLab` remains a working name; naming/trademark availability must be reviewed before public distribution.

## Contributing and policies

[Contributing](CONTRIBUTING.md) - [Code of conduct](CODE_OF_CONDUCT.md) - [Privacy](PRIVACY.md) - [Security](SECURITY.md) - [Development plan](DEVELOPMENT_PLAN.md) - [Third-party notices](THIRD_PARTY_NOTICES.md)

Original FocusLab code is licensed under [Apache License 2.0](LICENSE). Dependencies, Qt, and ML models retain their own licenses. Model files are not committed; download them explicitly using `--fetch-models`.

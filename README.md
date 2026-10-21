# FocusLab

**Know your workflow, not just your screen time.**

FocusLab is a local-first, open-source Windows desktop app for reviewing work patterns during study and development. It combines your session goal, PC activity, and optional webcam observations to distinguish estimated task-related activity, possible task deviation, time away, and insufficient evidence.

> **Status: v0.2 developer prototype.** The PySide6 app includes optional face/head-pose observation, mode-aware rules, optional task-relevance AI, live sessions, reports, and corrections. With consent, it also records and classifies PC/browser activity in the background and detects automatic sessions. ActivityWatch is not required. Thresholds and classification rules are hypotheses pending field validation (PR-12). Releases ship a portable `FocusLab.exe` zip with an in-app updater; an installer/uninstaller (PR-13) is not available yet. See the [engine design](docs/activity-engine.md).

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
| `uv run focuslab --relevance-selftest` | Load the optional task-relevance model, if installed, and test it. |
| `uv run focuslab --version` | Print the version. |
| `--data-dir <folder>` | Override the default `%LOCALAPPDATA%\FocusLab` data folder. |

Without a face model or camera, sessions can continue using PC observations. The app uses the network only for model downloads you start (the face model, and the task-relevance model from Settings) and for update checks and downloads you request or turn on (see [Updates](#updates)).

### Interface language

The app supports **English and Korean**. English is the default; the first-run setup lets you pick the language, and it applies right away. Later, choose **Settings > Appearance > Language** to save a preference, then restart FocusLab to apply it. A language change does not interrupt your current session or translate your saved goals, app names, or records.

`--language en|ko` or `FOCUSLAB_LANGUAGE=en|ko` overrides the saved preference for a run. Repository documentation is maintained in English. See the [translation guide](docs/internationalization.md).

### Optional browser site recording (Chrome / Edge)

1. In Settings > Browser site recording, choose **Install in Chrome** or **Install in Edge**. This asks for consent if needed and registers the Native Messaging host in HKCU without administrator rights.
2. Once the extension is listed in the Chrome Web Store or Edge Add-ons, the button opens that page; choose **Add**. Until then, the button copies the extension to `%LOCALAPPDATA%\FocusLab\browser-extension`, opens it in Explorer, opens a browser window, and copies `chrome://extensions` (or `edge://extensions`) to the clipboard. Browsers do not let other programs open that page directly. Paste the address, turn on Developer mode, and drag the folder onto the page.
3. While the browser is in front, the extension reports only the active tab's hostname (and, with separate consent, its sanitized page title). Program recording works without the extension.

To publish the extension to the stores, see [Publishing the browser extension](docs/browser-extension-store.md).

#### Optional browser page titles

FocusLab records only website hostnames (for example, `youtube.com`) by default. To display
individual video/document page titles in **Activity > Website / page** and activity exports,
and to let task relevance read them:

1. In **Settings > Browser site recording**, consent to browser site recording and install
   the FocusLab Activity Bridge for Chrome/Edge.
2. Enable **Save active page titles (optional)** and approve the separate consent prompt.
3. **Update an existing unpacked extension**: use **Install in Chrome/Edge** to refresh the
   staged extension folder, then press **Reload** on the existing extension at
   `chrome://extensions` or `edge://extensions`. An already loaded old extension will
   continue sending hostnames only until it is reloaded.
4. Open a public page such as a YouTube lecture. After the browser reports it, the
   Activity timeline shows the sanitized title next to the hostname. Old intervals
   stay hostname-only; titles cannot be reconstructed retroactively.

This is local-only and OFF by default. Some sensitive pages and excluded sites do not
record titles. Turning the option OFF deletes all previously saved titles while retaining
time and website records. Full URLs, query parameters and page text are never saved.

### Development checks

```powershell
uv run ruff check .
uv run pytest                                   # Unit, integration, and off-screen GUI tests
node --test "browser_extension/test/*.test.js"  # Extension tests
uv build
uv run python scripts/activity_smoke.py --seconds 60   # Real Win32 probe, temporary database
uv run python scripts/bench_activity.py                # Synthetic load and performance
uv run python scripts/eval_relevance.py                # Task-relevance accuracy
```

Measurements: [activity performance](docs/performance.md), [task relevance](docs/relevance-evaluation.md).

### Build FocusLab.exe

```powershell
uv run --group build python scripts/build_exe.py
```

This creates `dist\FocusLab\FocusLab.exe` (no console window, a folder of several hundred MB). Keep or copy the whole `dist\FocusLab` folder: the exe needs the `_internal` folder next to it. The face model is bundled when `assets\models\face_landmarker.task` exists. The exe accepts the same options as `uv run focuslab`; console output such as `--check` appears only when piped (`.\FocusLab.exe --check | more`). **Start at sign-in** and **Install connection** register the exe's own path, so turn them off and on again after moving the folder. **Install in Chrome/Edge** copies the bundled extension to `%LOCALAPPDATA%\FocusLab\browser-extension`, so moving the exe folder does not break a loaded extension.

### Source changes versus installed-app updates

A GitHub PR merged into `main` updates the source tree only. **It does not automatically update
a downloaded or already-running `FocusLab.exe` or reload Chrome/Edge extensions.** If
`git pull` prints "Already up to date", compare `git rev-parse HEAD` to the
latest `main` commit; to run the new source, use `uv sync --locked` and
`uv run focuslab`. The previously downloaded EXE stays unchanged.

GitHub Releases are deliberately versioned separately; **the latest release may predate the
latest main commit**. To update the packaged app, use a newer published release after its
tagged build succeeds. Changes in `browser_extension/` require refreshing the installed
extension folder and selecting **Reload** at `chrome://extensions` or
`edge://extensions`. New optional privacy features may also need additional consent in
Settings. See [PR and delivery policy](docs/merge-policy.md#user-visible-delivery-verification).

### Updates

Pushing a version tag publishes a release: bump `version` in `pyproject.toml` and `__version__` in `src/focuslab/__init__.py`, merge to main, then `git tag v<version> && git push origin v<version>`. The [Release workflow](.github/workflows/release.yml) checks that the tag matches both, runs the tests, builds `FocusLab.exe`, and attaches `FocusLab-<version>-win64.zip` and its `.sha256` to a GitHub Release.

In the app, **Settings > Updates** shows the version. **Check now** asks GitHub for the latest release; **Check for updates when FocusLab starts** (off by default) does the same a few seconds after startup and shows an **Update to v…** button in the sidebar. One click on **Update** (or that sidebar button) opens a progress window with a single bar over the download (MB done, speed) and unpacking; **Cancel** stops it and keeps nothing. It downloads the zip, verifies its SHA256, unpacks it next to the install folder, quits FocusLab (asking first during a session), swaps the folders and starts the new version. Records and settings live in `%LOCALAPPDATA%\FocusLab` and are kept. The folder path stays the same, so sign-in startup and the browser connection keep working. If the folder is still in use (for example a browser holding the native host open), the old version restarts and you can try again after closing the browser. When running from source, **Update** opens the release page instead.

GitHub Actions checks lint, tests, the diagnostic CLI, and package builds on a Windows runner. Camera hardware, permissions, and long-running GUI behavior require separate Windows testing.

## Implemented prototype features

- **Automatic activity recording:** consent-based recording without a timer. Foreground executable/product names are observed with `SetWinEventHook` plus one-second polling. Idle time (five minutes by default, backdated to last input), lock, sleep, logoff, user switching, and display-off events are handled. Sleep/unobserved time is not counted. Batch persistence limits abrupt-process-exit loss to about ten seconds. Tray recording, pause/resume, and optional sign-in startup are supported.
- **Optional browser sites:** Chrome/Edge MV3 extension with Native Messaging; background tabs and private windows are excluded.
- **Automatic classification:** development, study, documentation, research, communication, entertainment, gaming, productivity tools, break/inactive, and unclassified. Labels include confidence, evidence, and source. Ambiguous sites such as YouTube stay unclassified unless you choose a rule. App/site exclusions are supported.
- **Automatic sessions:** group activity by absence and sustained work-category changes, and calculate detours/return times. Overlapping manual sessions are marked without adding duplicate activity time. Detection is independent of the selected report range; exports recalculate from current activity and rules.
- **Activity:** daily overview, category/program/site totals, timeline, interval correction, automatic sessions, and 7/30-day statistics. Long-range reports run on a worker with its own database connection. Saving failures and last successful save times are visible.
- **Home:** automatic recording status and daily activity summary alongside manual focus-session metrics, plus recent sessions. The round **+** button in the bottom-right corner opens **New session** in a bubble right above it, on the page rather than in a separate window (goal, mode, target time, allowed apps folded into one line until you edit them, including selection from open apps, optional camera). Esc, **Cancel**, the **×** or a click elsewhere closes it.
- **Live session:** opened when a session starts and reached again from **Session in progress · Return** under the sidebar menu (Home's **+** becomes **Back to session in progress**, so only one session runs at a time). One-second estimates and evidence, confidence, foreground app, last input, head pose, in-memory preview with optional landmarks, timeline, pause, break, immediate correction, and finish. Closing the window can continue recording in the tray.
- **Session overlay:** an always-on-top panel (top-right by default, drag to move; the position is remembered) where three parrots sit on a branch above the session time without pauses and breaks, which is separate from the camera-based estimate. The parrots are the controls: red pauses or resumes, blue ends the session, and yellow starts or ends a break; pointing at one shows its action in a speech bubble. The top-right buttons collapse the overlay to just the time or hide it while the session continues (**Show overlay** brings it back). The parrots are drawn in code and only animate while the expanded overlay is on screen. They react to the session's estimate, never to a hunch: when it says *possibly off task* they stop and look at you, after 30 uninterrupted seconds they get cross, and they cheer when you are back. Uncertain estimates, being away, breaks and pauses reset this (they sleep through pauses). Turn reactions off, or reduce movement, under **Settings > Appearance**. Optionally (off by default), after a minute of uninterrupted off-task estimate one parrot leaves the branch and hovers in front of your work saying "Focus!": it covers part of the screen and catches clicks on itself (clicking it sends it back) but never takes keyboard focus. It returns as soon as you are back on task, pause or take a break, does not fly over full-screen programs, and flies at most once every five minutes; both times are adjustable. Turn it off under **Settings > Appearance > Session overlay**.
- **Reports:** seven-day state totals, per-session task-related share, possible deviations, return times, app switches, longest streak, coverage, interval evidence/corrections, goal-achievement self-report, JSON/CSV export, and deletion. Daily totals use actual observation timestamps.
- **Task relevance AI:** optional local judgment of whether the current activity serves the session goal, with a one-sentence explanation and your answers as feedback (see [How estimates work](#how-estimates-work)).
- **Settings:** separate consent controls, language, appearance and overlay options, data location, retention, complete export/deletion, browser setup and optional page titles, classification rules, camera device, model downloads, task relevance AI, updates, four-step calibration, and rule explanations. Withdrawing camera/PC observation consent also stops that observation in an ongoing session.
- **Recovery:** uncleanly ended sessions are marked interrupted on restart. Observation gaps become `UNKNOWN`.

## How estimates work

Sensors publish observations; the mode-aware [rule engine](src/focuslab/focus/rules.py) combines them over time and returns states with evidence codes.

- A non-allowed app for at least 15 seconds produces `POSSIBLY_OFF_TASK`; brief switches retain the previous state.
- A non-allowed app that may serve the task (a note-taking app such as Notepad, an AI assistant such as Claude, or another work/study tool) is `UNKNOWN` with a "check needed" reason instead: the app name alone neither confirms work nor establishes deviation, and neither does facing the camera.
- An absent face for 20 seconds (60 in reading/writing) plus at least 20 seconds without input can produce `AWAY`.
- Looking away for 15 seconds (30 in reading/writing) plus ten seconds without input can produce `POSSIBLY_OFF_TASK`. **Looking down alone does not trigger this estimate.**
- Camera off, occlusion, darkness, errors, and stale observations are missing evidence. Face observations expire after two seconds and PC observations after three; camera loss alone does not establish deviation or absence.
- Entering task-related/unknown states requires three seconds of sustained evidence to prevent flicker. A user-requested break is immediate.
- An allowed browser without site details is `UNKNOWN` (it may show any site), not task-related. Allowed-app lists can include sites such as `github.com`; with the browser extension connected, the reported site decides.
- **Task relevance** ([relevance engine](src/focuslab/relevance/engine.py)) compares the session goal with the current activity: page-title rules, an optional local language model (Settings → Task relevance AI) and the order and duration of recent activities. It needs the optional page-title consent for browser pages. Only evidence acts: an activity tied to the goal counts like an allowed app (for example notes opened right after a related lecture), and a page judged unrelated to the goal (for example a gameplay compilation while studying AR) produces `POSSIBLY_OFF_TASK` after 60 seconds, and only while someone is evidently at the PC. An uncertain or missing relevance result changes nothing. During a session the Session page explains the judgment in a sentence and takes your answer (helps the task / not related / not sure), which outranks it. Measurements and limits: [docs/relevance-evaluation.md](docs/relevance-evaluation.md).

Automatic recording uses input-based idle detection, so reading or watching a lecture without input may count as idle. Work-category totals are category sums; manual-session estimates also consider your goal and allowed apps. These are different measurements, and the UI explains the distinction.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/focuslab/` | Entry point, paths/defaults, localization, demo sensors/data, model download, updater, sign-in startup |
| `domain/` | States, observations, sessions, segments, and sensor/clock contracts |
| `camera/` | Capture, face landmarks, head pose, and calibration |
| `activity/` | Win32 probes/hooks, recorder, classifier, automatic sessions, camera overlays, statistics |
| `browser/`, `browser_extension/` | Native Messaging host/protocol, Chrome/Edge registration, MV3 extension and JS tests |
| `focus/` | Sensor fusion, mode-aware rules, evidence, and metrics |
| `relevance/` | Task relevance: activity context, title rules, optional local embedding model, explanations, feedback |
| `storage/` | SQLite, migrations, and repositories |
| `services/` | Session/worker orchestration, activity reporting, export/deletion |
| `ui/` | Window, pages, dialogs, tray, shared widgets, background report worker; `ui/mascot/` draws and directs the overlay parrots |
| `locales/` | Korean translations of English application messages |
| `scripts/` | Real-device smoke check, benchmarks, relevance evaluation, exe build, extension packaging |
| `assets/models/` | Optional models (face model via `--fetch-models`, relevance model via Settings); not committed |
| `tests/unit/`, `tests/integration/`, `tests/e2e/` | Unit, pipeline/persistence, and off-screen GUI tests |
| `tests/data/` | Labeled goal/activity pairs for relevance evaluation |
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
| — | English/Korean interface, session overlay and parrots, optional page titles | Implemented |
| — | Task relevance AI (local rules, optional embedding model, explanations, feedback) | Implemented in v0.2.0 |
| PR-10-11 | Optional phone detection, personalization, quiet coaching | Planned; relevance feedback and parrot reactions cover part of it |
| PR-12-13 | Field validation, performance/packaging, Windows installer | Partly done: portable exe, GitHub releases and updater ship; field validation, installer/uninstaller and store listings remain |

The [development plan](DEVELOPMENT_PLAN.md) defines scope and completion criteria. Implement changes on feature branches, target `main` when integrating them, validate, and review before merging. `FocusLab` remains a working name; naming/trademark availability must be reviewed before public distribution.

## Contributing and policies

[Contributing](CONTRIBUTING.md) - [Code of conduct](CODE_OF_CONDUCT.md) - [Privacy](PRIVACY.md) - [Security](SECURITY.md) - [Development plan](DEVELOPMENT_PLAN.md) - [Third-party notices](THIRD_PARTY_NOTICES.md)

Original FocusLab code is licensed under [Apache License 2.0](LICENSE). Dependencies, Qt, and ML models retain their own licenses. Model files are not committed; download them explicitly (`--fetch-models`, or Settings > Task relevance AI).

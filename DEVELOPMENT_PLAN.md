# FocusLab: Windows work-pattern observation development plan

> Windows open-source implementation plan v1.0. Baseline date: 2026-10-20. See the [README roadmap](README.md#development-roadmap) for implementation status.
>
> Target: Windows 11 first; Windows 10 requires separate compatibility testing. Single-user, local-first, without mandatory accounts or cloud services.
>
> Scope: optional webcam behavior observations, PC activity, per-session pattern analysis, and consent-based automatic activity recording ([section 18](#18-v02-extension-native-windows-activity-tracking-engine)).
>
> No ADHD diagnosis, treatment, or medical-device functionality. A camera alone cannot directly measure attention.

## 0. Mission, differentiation, and open-source principles

**Tagline:** *Know your workflow, not just your screen time.*

**Mission:** help people understand when and why they leave a chosen task and use their own feedback to make returning easier.

### Product differentiation

- Do not equate facing the screen with attention. Consider the relationship between the current goal and active apps/sites first.
- Support coding, lectures, and paper reading/writing; looking down alone must not establish task deviation.
- Explain estimates and allow immediate correction. Corrections apply only to that user's records.
- Report evidence and limitations alongside work continuity, possible-deviation time, return time, and unknown time.
- Do not require accounts, cloud processing, or continuous surveillance. Keep source open and sensors replaceable.

**Naming:** FocusLab is a working name. Other services use it; review repository names, domains, and trademarks before public distribution. An open-source license does not grant rights to another party's trademarks.

**Platform:** Windows 11 x64 is the development, CI, and release-validation target. Windows 10 is community best effort rather than an official commitment; the original plan notes its general-support end date of 2025-10-14.

### Open-source principles

- Publish the repository from PR-00 with Apache-2.0 for original code and LICENSE, NOTICE, README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, and PRIVACY.
- Review the actual distribution method for PySide6/Qt's LGPLv3/GPLv3/commercial terms. Check MediaPipe and each individual model's license and redistribution terms separately; document them in THIRD_PARTY_NOTICES.
- Pin dependencies, verify model SHA256 hashes, preserve notices, generate an SBOM if feasible, and provide private vulnerability reporting.
- Provide focused issues/PRs, Windows reproduction steps, English repository documentation, and a guide for English/Korean interface translations.
- Protect `main`; integrate feature branches through tested, reviewed PRs.

## 0-1. One-sentence objective

Build a local desktop app that combines face/head-pose/presence and Windows foreground/idle observations during user-started study/development sessions, optionally adds browser-hostname context, displays task-related/possibly-off-task/away/unknown intervals, and incorporates the user's corrections.

### Required principles

1. The camera starts only in an explicitly enabled manual session and is released immediately when disabled. Never capture covertly or continuously.
2. Do not save raw video, audio, typed content, or screenshots by default. Store only local events and necessary aggregates.
3. Looking away is not proof of task deviation. Camera loss/occlusion is missing evidence, not an automatic away judgment.
4. Avoid distracting the user. Notifications default off or infrequent, and breaks remain distinct from work.
5. Put models behind replaceable interfaces and keep UI, analysis, and storage loosely coupled.
6. Explain collected data, permissions, retention, and immediate deletion controls.

## 1. Product definition and scope

### User scenario

1. Choose a goal such as solving algorithm problems and start a 25-minute session.
2. Allow relevant apps such as VS Code, a lecture player, and official documentation.
3. Optionally observe face presence and head direction with the webcam.
4. Combine observations once per second, preserving `UNKNOWN` when evidence is ambiguous.
5. Review task-related duration, app switches, possible deviations, time away, and corrections.
6. Correct an interval as normal work, reading below the screen, or a break.

### v0.1 MVP

- Windows 11 x64, single-user local execution.
- Session start/pause/resume/finish, goal/mode/allowed apps.
- Camera selection/preview, face detection, head pose, absent/uncertain observations.
- Foreground programs, app switches, and OS idle detection.
- Event timeline, session summary, simple daily/weekly reports.
- On-device processing, no raw video storage, export/deletion.

### Browser-context boundary

The desktop app alone identifies a browser process, not whether the current page is documentation or a social site. With an optional, explicitly enabled extension, send only the active tab's hostname (plus, with separate consent, a sanitized page title) and compare it with allowed sites. Do not collect complete browsing history, URL paths, or search terms.

The initial browser work package PR-09 is superseded by PR-C in section 18, which also supports Edge. Without it, explain the limit of process-level browser observations.

### v0.2

- Optional phone-object detection only when visible in the camera frame, with environment-specific calibration.
- Mode-aware rules and personalization based on user feedback.
- Tray behavior, notification controls, and recovery. Some of this is already implemented by the activity engine.

### v1.0

A distributable Windows package, settings migration, robustness tests, measured false-positive/performance results, accessibility, failure handling, and diagnostics without sensitive information.

### Explicit exclusions

- ADHD probabilities, diagnostic/medical scores, emotion recognition, and face identity recognition.
- Continuous background video, keylogging, screen recording, and observation of other people without consent.
- Mandatory cloud uploads, accounts, cross-device sync, or automatic paid billing.
- Reading phone-screen contents or promising precise screen-pixel gaze coordinates from a webcam.

## 2. Technical decisions

| Layer | Technology | Rationale |
| --- | --- | --- |
| Language/environment | Python 3.11, uv, pyproject.toml, lock file | Windows/ML integration and reproducible setup |
| Desktop UI | PySide6 / Qt Widgets | Windows MVP, tray, thread separation |
| Camera | OpenCV | Capture, color conversion, frame control |
| Face landmarks | MediaPipe Tasks FaceLandmarker | Landmarks and face transformation matrices |
| Optional phone detection | MediaPipe ObjectDetector with a verified phone-class model | Separate feature requiring validation |
| PC events | pywin32, psutil, ctypes | Foreground process and idle/system events |
| Storage | Standard-library sqlite3, WAL | No server, user-controlled files |
| Quality | pytest, pytest-qt, ruff; gradual type checking | Domain, rules, integration, GUI validation |
| Distribution | PyInstaller ([scripts/build_exe.py](scripts/build_exe.py)), portable zip per GitHub Release | Verify packaging on actual Windows environments |
| CI | GitHub Actions Windows runner | Lint, tests, diagnostic CLI, build |
| Localization | English source messages, packaged Korean catalog | Stable stored codes; English/Korean interface |

Pin versions only after validating compatibility on Windows Python 3.11. Keep model source/hash/license metadata with any future binary bundle; the face model is bundled into a local exe build only when it was downloaded beforehand, release zips do not include it, and the task-relevance model is downloaded only on request from Settings.

### Environment and dependency constraints

- Windows 11 x64 with versions locked in `uv.lock`.
- Do not assume administrator rights. If camera permission is denied, continue with PC observations.
- Inference works offline; initial model installation can require a user-requested download.

### Process and thread boundaries

- The Qt main thread only updates UI and handles input.
- Camera capture and face inference use separate workers and release device handles on stop.
- Session rules run on a one-second schedule; sensors expose their latest observation.
- The automatic recorder uses its own worker/SQLite connection; Windows notifications use a message-window thread.
- Activity reports use a worker with a separate database connection to avoid blocking the UI or session lock.
- The browser's Native Messaging host is a separate process; it stores latest validated state for the recorder.

### Pipeline

```text
Webcam -> OpenCV capture -> FaceLandmarker -> FaceObservation ------+
                                      Optional PhoneDetector -----+
Windows foreground/idle -> ActivityObservation --------------------+
    -> TTL fusion -> mode-aware rules -> state/evidence -> SQLite
    -> PySide6 session view and reports
```

### Data contracts

[domain/models.py](src/focuslab/domain/models.py) defines states, face observations (presence, calibrated yaw/pitch, quality), and PC observations (process, allowed status, idle, lock). Missing values are `None`: missing evidence, not evidence of task deviation.

Sensors publish observations only. The rule engine returns state and evidence codes using observations, mode, and time windows. Persist UTC time, monotonic session offsets, rule/classifier versions, confidence, and unknown reasons. Never retain raw frame/face-coordinate data as historical records.

## 3. Code structure

Follow the [README layout](README.md#repository-layout). Future phone detection belongs behind a camera sensor interface. Browser integration supplies observations rather than making UI decisions. Synthetic events in `focuslab.mock_sources` are default test data; do not commit actual video without consent.

## 4. Data model

[storage/migrations.py](src/focuslab/storage/migrations.py) is authoritative.

- `session`: goal, mode, target time, UTC start/end, status, camera flag, rule version, pauses, self-report.
- `session_allowed_app`: session/process associations and display labels.
- `state_sample`: per-second state, confidence, evidence, app name, actual UTC epoch timestamp (`at_ms` from v5).
- `event`: same-state intervals with offsets, severity, evidence, app names, and source.
- `feedback`: one correction/comment per interval.
- `relevance_rule`: user answers about whether an activity helps a goal (v7).
- `settings`: key/value preferences and update timestamps.
- `migration`: applied schema versions/timestamps.

Default data folder: `%LOCALAPPDATA%\FocusLab`, overridable with `--data-dir` or `FOCUSLAB_DATA_DIR`. Enable foreign keys, WAL, explicit transactions, and tested migrations. Preview frames remain in memory. Provide retention, export, and complete record deletion. Section 18 adds automatic activity tables.

## 5. States and estimation rules

### Modes

- `CODING`: IDE, documentation, allowed browser work; looking away alone does not establish deviation.
- `LECTURE`: viewing without input can be expected.
- `READING_WRITING`: books/notes; allow looking down and wait longer before estimating absence.
- `CUSTOM`: user-defined allowed programs and preferences.

### Initial rules: hypotheses, not medical criteria

| Condition | Candidate | Safeguard |
| --- | --- | --- |
| Error, blocked camera, obscured face | Unknown camera evidence | Do not infer absence from camera loss |
| Face absent for 20 seconds plus no PC input | `AWAY` may apply | Longer reading/writing threshold |
| Sustained looking away plus no input | `POSSIBLY_OFF_TASK` may apply | Looking down alone never qualifies |
| Non-allowed app for 15 seconds | `POSSIBLY_OFF_TASK` | Apply allowed-app/site context |
| Allowed app with usable face evidence | Estimated `ON_TASK` | Does not prove learning or attention |
| User requests break | `BREAK` | Report separately |
| Phone visible (future) | Phone-observed event | Presence alone does not prove use or deviation |

Use hysteresis and minimum dwell times to prevent flicker. Allow immediate correction. Camera-free sessions must remain usable. Treat unobserved system-lock/sleep/interruption periods as unknown evidence; recover interrupted sessions on restart.

## 6. Metric definitions

Avoid attention scores or excessive numerical claims about psychological concepts. The primary metric is **observed task-related activity time**.

- Total session length: end minus start; explain whether pauses are included.
- Estimated task-related time: accumulated `ON_TASK`; not proof of attention.
- Possibly off-task time: accumulated `POSSIBLY_OFF_TASK`.
- Away time: report `AWAY` separately.
- Unknown time/share: report missing evidence explicitly; camera-off is not a low score.
- Task-related share: `ON_TASK / (ON_TASK + POSSIBLY_OFF_TASK)`; unavailable for zero denominator. Show coverage alongside it and separate away/break/unknown time.
- Return time: end of a possible-deviation interval to the next task-related interval. Preserve no-return cases ending in a break/interruption.
- Evidence: show contributing observations, mode, quality, and rule version. Favor unknown when confidence is insufficient.

## 7. Work-package roadmap

Work-package labels below are not GitHub PR numbers. Implement, test, validate on Windows, review, and merge before the next dependent stage. Recover failures before proceeding.

| Package | Purpose | Scope and required completion criteria |
| --- | --- | --- |
| PR-00 | Open-source bootstrap | Policies/license, environment, PySide6, mock sensors; another Windows 11 PC can install/test/open the empty UI; licensing review tracked |
| PR-01 | Session lifecycle and SQLite | Explicit lifecycle, schema/migrations; transition and abrupt-exit recovery tests |
| PR-02 | Camera capture | Selection/preview, permission errors, worker release; open/close/disconnect recovery with no video storage |
| PR-03 | Face landmarks | Presence, landmarks, quality; ten-minute responsive run and model-error fallback |
| PR-04 | Head pose/calibration | Direction, four-step calibration, unknown handling; repeatable left/right/down observations |
| PR-05 | Windows activity | Foreground, idle, allowed apps; switch/idle/lock/sleep handling, no sensitive titles |
| PR-06 | Context-aware engine | Modes, state machine, evidence, TTL/hysteresis; at least 25 synthetic rule tests and camera-off operation |
| PR-07 | Live dashboard | Home/session/timeline/health/controls; stable 25-minute session, recording while minimized |
| PR-08 | Reports and privacy controls | Daily/session metrics, corrections, deletion, JSON/CSV; correct totals and deletion -> v0.1 MVP |
| PR-09 | Optional browser extension | Consent-based active hostname, MV3/Native Messaging; install/remove, private mode, origin/schema/permission checks; replaced by PR-C |
| PR-10 | Optional phone detection | Verified phone model; independent enable/disable, false-positive/negative records, no image leakage |
| PR-11 | Personalized feedback/quiet coach | Mode calibration, corrections, notification cooldown; useful personalization without excessive alerts -> v0.2 beta |
| PR-12 | Field validation/robustness | User labels, failures, long runs, resources; measured limits and new-account/environment E2E |
| PR-13 | Windows distribution | Model/dependency notices, build/installer/uninstaller/releases; works on Windows 11 without Python -> v1.0 |

### Implementation details

- PR-00: establish `python -m focuslab` / `uv run focuslab`, conventions, versions, event contracts, and sensor-free UI testing.
- PR-01: implement `IDLE -> RUNNING -> PAUSED -> RUNNING -> FINISHED`; recover or mark interrupted sessions after crashes.
- PR-02-04: separate rendering/inference, optional landmark display, metadata-only storage, center/left/right/down calibration.
- PR-05: process tracking cannot reliably identify browser tabs; keep hostname observation in a separate minimal-permission extension.
- PR-06: expire stale observations rather than holding values forever. Describe estimated task relation rather than actual attention percentages.
- PR-07-08: make correction easy to access; emphasize transitions and state duration rather than scores.
- PR-09: transmit only active hostname through Native Messaging, not history/URL paths; validate registration, origin, message schema/size, shutdown, private-mode exclusion, and extension-absent fallback.
- PR-10: verify an actual phone class. Do not guess about occluded/out-of-frame objects or equate detection with phone use.
- PR-11: notifications default off/minimal, use per-cause cooldown, and remain limited during breaks/exams/lectures.
- PR-12-13: check camera permissions across Windows accounts, preserve model/license metadata, and ship checksums/changelogs.

## 8. Screen requirements

1. Home: today's automatic recording and manual sessions, estimated work, start button, quick mode selection.
2. Live session: goal/time, camera/foreground status, estimated state, pause/finish/correction.
3. Report: interval timeline, switches, possible-deviation evidence, corrections, self-reported goal achievement.
4. Settings: language, camera/consent/calibration, allowed apps, notifications, retention/export/deletion.
5. Activity: automatic timeline, classifications/corrections, sessions, program/site/category totals, range statistics.

Use wording such as estimated task-related share, looking away, and unknown. Do not show diagnostic or attention scores. English and Korean must use the same metrics and state codes; language preferences apply on restart to preserve live sessions.

## 9. Tests and quality gates

### Evidence and accuracy

Compare 10-20 sessions with user-labeled reference logs. Do not save raw video by default; any recorded test dataset requires separate consent. Evaluate face absence, app switches, and user-marked deviations separately. Report precision/recall, false alarms per hour, unknown share, coverage by sensor, CPU/memory/battery, and limitations. Repeat the same evaluation after tuning. Do not claim validated attention accuracy or repurpose results for diagnosis.

### Required automated checks

- Unit: lifecycle, totals, modes, TTL, ambiguous inputs, deduplication.
- Integration: scripted sensors through fusion, SQLite, and consistent reports/exports.
- GUI: start/pause/resume/finish, permission denial/disconnection/errors, no remaining workers after shutdown.
- Privacy regression: no footage/content storage and no observation without the relevant consent, including mid-session withdrawal.
- Localization: English/Korean coverage, compatible placeholders, persisted preference, stable enum/data keys, and correct date/time labels.

### Real-device protocol

In 10-20 self-labeled sessions, repeat coding, screen lectures, paper reading/writing, brief phone checks, leaving the desk, covering the camera/darkness, minimizing, Windows lock, sleep/wake, and device disconnection. Compare observable absence/switches/user-marked deviations rather than an abstract ground truth of attention. Do not claim accuracy without labels.

### Initial performance targets

- No UI freeze/crash during a 25-minute session on a mainstream laptop.
- Measure camera inference CPU/memory; reduce sampling if necessary.
- Release device handles after camera use.
- Keep false notifications low (initial aspiration: no more than one per thirty minutes), then revise using evidence.
- Report `AWAY` and `POSSIBLY_OFF_TASK` precision/recall separately; set targets after baseline measurement.
- No corrupted database on restart; tested migration/backup/recovery paths and bounded batch-loss expectations.

## 10. Security and privacy

Obtain clear, separate consent and show camera/recording state in both window and tray. Do not collect raw images/audio/screens/typed content/history. Keep frames in memory; do not implement recording/upload features. Release workers/devices on pause/stop/withdrawal. Logs must exclude personal data, face coordinates, URLs, and raw imagery. Provide local export/deletion/retention. Support self-observation only, not nonconsensual or remote surveillance. Native Messaging requires origin allowlisting, message-size limits, and input validation. Never describe results as medical judgments.

## 11. Definition of done

**v0.1 MVP:** user can choose goal/mode/camera, complete a stable 25-minute session while minimized, inspect presence/unknown/activity/idle states and interval evidence, correct classifications, export/delete records, and continue without a camera. Raw video is not saved.

**v1.0:** optional phone observation accurately communicates uncertainty; notification/mode/calibration personalization works; 10-20 validation sessions document false positives/negatives and limits; install/run/uninstall succeeds without Python; CI, tags, changelog, installation/privacy documentation are available.

## 12. Tentative schedule

Assume one developer working 10-15 hours/week; completion criteria matter more than dates.

| Week | Packages | Outcome |
| --- | --- | --- |
| 1 | PR-00-02 | Repository, sessions, camera |
| 2 | PR-03-04 | Face observations and calibration |
| 3 | PR-05-06 | Windows activity and contextual rules |
| 4 | PR-07-08 | Dashboard/data controls, v0.1 MVP |
| 5 | PR-09 | Optional extension and transport validation |
| 6 | PR-10-11 | Optional phone observation, feedback/notifications |
| 7 | PR-12 | Field validation, performance, failure handling |
| 8 | PR-13 | License review, installer, v1.0 |

Native Messaging installation, MediaPipe packaging, hardware variation, and false positives can extend this beyond eight weeks.

## 13. Development process and PR template

Keep `main` runnable. Use a scoped feature/fix branch, preserve UI/engine contracts, run lint/unit/integration checks, and record real-device checks when relevant. Follow the [PR template](.github/PULL_REQUEST_TEMPLATE.md): problem/result, changes, validation, privacy/performance, limits, follow-ups. Exclude raw camera images from screenshots. Merge after CI/review; hide unfinished features behind disabled flags. Check the base branch explicitly for stacked work.

## 14. Development environment

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Lock versions in `uv.lock`; validate additions on Windows Python 3.11 and update [third-party notices](THIRD_PARTY_NOTICES.md).

## 15. Future extensions

- Richer, user-correctable browser categories; start with minimum hostname collection.
- Task relevance currently uses title rules plus an optional local embedding model ([relevance evaluation](docs/relevance-evaluation.md)); optional local LLM summaries remain future work, constrained to explainable observed numbers, without diagnostic claims or overinterpretation.
- Optional wearable sleep/activity integrations with separate consent and validation.
- Better interaction patterns for switches, breaks, and goal achievement.

## 16. Repository documentation and contribution flow

PR-00 establishes license/notices, README, contribution/conduct/security/privacy policies, issue/PR templates, and CI. See [CONTRIBUTING.md](CONTRIBUTING.md).

Release sequence: local v0.1 prototype, v0.2 browser/phone work, then validated Windows v1.0. Include checksums, changelog, notices, and an SBOM if feasible. The in-app updater checks only on request or, if enabled, at startup (off by default) and verifies the release zip's SHA256.

### Before starting

Review naming availability, prepare a Windows 11 PC/webcam, confirm non-admin camera/foreground access, document Qt/model distribution terms, and test that logs omit sensitive information. Agree that uncertainty remains explicit instead of forcing every behavior into task-related/off-task labels.

## 17. Official references

- [MediaPipe Face Landmarker for Python](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python)
- [MediaPipe Object Detector for Python](https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector/python)
- [PySide6 deployment](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
- [GetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow)
- [GetLastInputInfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)
- [Windows 10 end of support](https://learn.microsoft.com/en-us/lifecycle/announcements/windows-10-end-of-support)
- [Qt for Python](https://doc.qt.io/qtforpython-6/)
- [Apache 2.0](https://choosealicense.com/licenses/apache-2.0/)
- [GitHub community profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)

## 18. v0.2 extension: Native Windows Activity Tracking Engine

> Extension baseline: 2026-10-20. Detailed [analysis and design](docs/activity-engine.md).

### Changes to the plan

- After explicit first-run consent, PC foreground/idle/lock/sleep and optional browser hostnames can be recorded automatically in the background, beyond manual sessions. Pausing or declining consent stops those queries/writes.
- The camera remains limited to manually started focus sessions. Overlay presence/head observations on coincident activity without equating head direction with deviation.
- Implement collection, storage, classification, and dashboard in FocusLab. ActivityWatch's public feature descriptions informed scope, but no code is copied and no installation is required.
- Replace PR-09 with PR-C for Chrome and Edge. Phone/eye-closure observation remains outside this extension.

### Additional work packages

| Package | Scope | Completion criteria |
| --- | --- | --- |
| PR-A | Schema v2, Win32 probe, recorder, foreground events | Switching/merging/storage unit tests and real-device intervals |
| PR-B | Backdated idle, lock/sleep/logoff/clock changes, recovery/startup/tray/onboarding | Sleep excluded; bounded abrupt-exit data loss |
| PR-C | MV3, Native Messaging, install/remove, validation/deduplication | Program recording works without extension; private windows excluded |
| PR-D | Ten categories, rules/confidence/evidence/source, corrections/exclusions | Ambiguous sites stay unknown; rules reflect corrections |
| PR-E | Automatic sessions, manual-session/rule/camera integration | Idle/category splits; no duplicate timeline totals |
| PR-F | Daily overview/timeline, app/site and 7/30-day statistics | Totals do not exceed observed elapsed time |
| PR-G | Retention/export/deletion, performance, stability/docs/CI | Document measured resource use and limitations |

### Implementation status

| Package | Branch / GitHub PR | Snapshot |
| --- | --- | --- |
| PR-A | `feat/activity-collector`, #4 | Implemented and tested |
| PR-B | `feat/idle-system-events`, #5 | Implemented and tested; later integrated into main via #8 |
| PR-C | `feat/browser-tracker`, #6 | Implemented/tested, including Edge; later integrated via #8 |
| PR-D | `feat/activity-classifier`, #7 | Implemented and tested |
| PR-E | `feat/auto-sessions`, #9 | Implemented and tested |
| PR-F | `feat/activity-dashboard`, #10 | Implemented and tested |
| PR-G | `chore/activity-stability-release`, #11 | Retention/export/deletion and [performance measurements](docs/performance.md) |
| Task relevance | #36–#42, released in v0.2.0 | Implemented and verified; see [relevance evaluation](docs/relevance-evaluation.md) |

Migrations preserve earlier data: v2 adds app/activity_span/system_event, v3 browser_state/domain, v4 classification_rule/activity_feedback, v5 auto_session/state_sample.at_ms, v6 optional browser/activity page titles, and v7 relevance_rule. Subsequent fixes improve consent withdrawal, range-independent sessions, exports, daily attribution, and camera coverage. English/Korean localization adds a settings preference without changing schema or stored codes.

### Remaining work

- PR-12: validate classifier/session thresholds (five-minute break, five-minute category change, two-minute minimum) and idle assumptions with real user labels. Exercise sleep/lock/UWP/multi-monitor and manual-session cases.
- PR-13: the packaged exe registers itself as native host and sign-in startup, and portable releases with an updater ship. Remaining: publish store listings and fill in their extension IDs (`STORE_IDS`), and build/validate an installer/uninstaller with browser-connection diagnostics tested on a first-time user's complete flow.
- UX: move Activity's detail tables and long-range charts into collapsible sections or tabs, and describe numeric confidence as rule confidence rather than calibrated probability until field validation.
- PR-10: optional phone detection and eye/blendshape observations remain separate future work.

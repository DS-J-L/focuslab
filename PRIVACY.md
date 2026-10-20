# Privacy principles

FocusLab has no accounts, cloud storage, or analytics uploads. Records stay in a local SQLite database on your PC. Network access is limited to the face model download you explicitly request with `focuslab --fetch-models` or the Settings button, and to update checks. An update check asks GitHub (`api.github.com`) for the latest FocusLab release; it runs only when you press **Settings > Updates > Check now** or turn on **Check for updates when FocusLab starts** (off by default). Like any web request it reveals your IP address and FocusLab version to GitHub; no records are sent. Downloaded updates are verified against the release's SHA256 before installing.

The browser extension communicates with FocusLab on the same PC through Chrome Native Messaging (standard input/output). It does not open a network port.

## When and what is observed?

Automatic recording, browser recording, manual-session PC observation, and camera observation have separate consent controls. You can disable or withdraw them in Settings.

| Observation | When | Read | Not collected or recorded |
| --- | --- | --- | --- |
| Automatic Windows activity | After consent, while FocusLab runs, including in the tray. Pausing stops OS queries. | Foreground executable name and product description, time since keyboard/mouse input, lock/sleep/logoff/user-switch/display events | Window titles, document names, full URLs, typed content, mouse coordinates, screen contents |
| Browser sites (optional Chrome/Edge extension) | With browser and automatic-recording consent, after you install the extension | Active tab **hostname** in the focused browser window (for example, `github.com`); **page title only after separate explicit opt-in** | Full URL, paths, search terms, page contents, browsing history, background tabs, InPrivate/incognito windows |
| Manual-session PC observation | Once per second during a focus session you start | Foreground process name, time since last input, lock status, and current site if automatic recording provides it | The sensitive contents listed above |
| Optional camera | Only during focus sessions you start; released on pause, finish, camera-off, or consent withdrawal | Face presence, head angles, observation quality | Identity recognition, emotion recognition, diagnosis; video, photos, and face coordinates are not saved |

- Executable paths may be inspected in memory to identify a Steam/Epic/game-library folder; the paths are discarded and not stored.
- The camera never runs as part of background automatic recording. Observations overlap with automatic activity only during manual focus sessions. Only estimated absence reduces attended work time; looking away alone does not establish task deviation.
- Camera frames are processed in memory without disk storage or transmission.
- Excluded programs/sites leave only unnamed **Excluded** time in the automatic activity timeline. Adding an exclusion does not erase historical records; delete existing records separately if needed.
- Browser messages with unexpected fields (such as `url`) are rejected. Page-title fields are validated and discarded when separate title consent is off; withdrawing it clears current and historical page-title fields while retaining activity durations. Without consent or while recording is paused, current browser state is not stored. Closing the browser clears its current state.
- During a focus session the session goal is compared with the current page title (only with title consent) to estimate task relevance. Rules run by default; the optional **Task relevance AI** uses a small language model downloaded only after you turn it on in Settings, and it runs on this PC only. Titles and the vectors derived from them are kept in memory only and are dropped when title consent is withdrawn; Settings → Remove model deletes the model.
- Withdrawing camera or manual PC-observation consent also stops that observation in an ongoing session. Automatic PC recording has its own separate consent switch.

## What is stored?

Default location: `%LOCALAPPDATA%\FocusLab\focuslab.db`. Override with `--data-dir` or `FOCUSLAB_DATA_DIR`.

- **Activity intervals:** start/end, active/idle/locked state, executable/product names, hostname, optional separately consented page title, category/confidence/evidence/source/classification time, and corrections.
- **System events:** recording start/stop/pause, lock/unlock, sleep/wake, logoff, clock changes, and unclean-exit recovery.
- **Automatic sessions:** derived summaries of activity intervals; these can be recalculated.
- **Browser state:** latest hostname and (only after separate title consent) current tab title per browser profile. Title consent withdrawal clears title values in both current state and saved activity.
- **Focus sessions:** goal, mode, target time, start/end, pauses, camera setting, rules version, goal-achievement self-report, allowed apps, per-second estimates/confidence/evidence/foreground app/timestamp, state intervals, and corrections.
- **Settings:** consent, interface language, idle threshold, classification rules, exclusions, camera index, head-pose calibration, retention, and related preferences.
- **Task-relevance rules (only when you tick "Also use for similar goals"):** key words of the session goal, the page (site and page title), site or program you answered about, and your answer. Rules naming a page title are deleted when page-title consent is withdrawn; Settings → Task relevance AI lists and deletes them. One-time answers are kept only in memory, apart from the corrected state interval.

Windows registry entries under HKCU are created only when you enable sign-in startup or install the Chrome/Edge Native Messaging connection. Their controls remove those entries when disabled/uninstalled.

## Export, deletion, and retention

- Settings provides complete JSON export (focus sessions and automatic activity), focus-session CSV, activity CSV, and **Delete all records**.
- Complete deletion removes sessions, activity, automatic sessions, system events, browser state, and corrections. Settings, consent, classification rules, and exclusions remain.
- Reports provides per-session JSON/CSV export and deletion. Activity provides interval classification corrections.
- A configured retention period deletes expired sessions and activity at startup and when applied. The default is unlimited retention.
- Removing the entire app data folder also removes preferences and consent.

Changing the interface language affects labels and formatted explanations. It does not translate or rewrite saved goals, app names, observations, stable state/category codes, or historical user content.

## Features we do not provide

- Nonconsensual observation of other people or remote surveillance.
- Recording typed content, screen contents, Windows application window titles, or full URLs. Active browser tab titles are optional and require separate consent.
- Attention scores, ADHD risk scores, or medical/psychological judgments. Every metric is an estimate of observable behavior.

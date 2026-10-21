# Task relevance: evaluation, performance and privacy report

Covers the task-relevance engine added in PR #36–#41 and verified in PR #42 (released in
v0.2.0). Every number here comes from `scripts/eval_relevance.py` or the test suite on the
machine and data below; none is a measured accuracy on real users.

## Setup

| | |
| --- | --- |
| Machine | Windows 11 Pro 10.0.26200, Intel Core i9-14900HX (32 threads), 32 GB RAM |
| Runtime | Python 3.11.14, onnxruntime 1.31.0 (CPU, 1 intra-op thread), sentencepiece 0.2.2 |
| Model | `intfloat/multilingual-e5-small`, quantized ONNX (`model_qint8_avx512_vnni.onnx`), revision `614241f`, MIT |
| Title data | `tests/data/relevance_eval.csv` (90 goal–title pairs, 10 goals; used to calibrate) and `tests/data/relevance_holdout.csv` (30 pairs, 5 other goals; checked only) |
| Session data | 5 scripted sessions in `scripts/eval_relevance.py` (7,200 s, truth label per second), run through the real `SessionService` with mock sensors |

All data is synthetic. Thresholds were tuned on the calibration set and confirmed, not re-tuned,
on the holdout set.

```powershell
uv run python scripts/eval_relevance.py               # title sets, latency, memory
uv run python scripts/eval_relevance.py --scenarios   # sessions, second by second
uv run python scripts/eval_relevance.py --long-run 8  # 8 simulated hours
uv run focuslab --relevance-selftest                  # installed model, also in FocusLab.exe
```

## Title-level results

"False off-task" (a related title judged `POSSIBLY_UNRELATED`) is the error that matters most;
"false related" lets a detour pass as work.

| Set | Engine | related → RELATED | unrelated → POSSIBLY_UNRELATED | false off-task | false related | left UNCERTAIN |
| --- | --- | --- | --- | --- | --- | --- |
| calibration (90) | rules | 15/50 | 13/40 | 0 | 0 | 69% |
| calibration (90) | rules + model | 34/50 | 13/40 | 0 | 0 | 48% |
| holdout (30) | rules | 3/15 | 6/15 | 0 | 0 | 70% |
| holdout (30) | rules + model | 10/15 | 6/15 | 0 | 0 | 47% |

Model score = cosine(goal, title) − max cosine(leisure topic, title), with the goal encoded as an
e5 `query:` and the title as a `passage:`. Raw cosine overlapped (related min 0.78, unrelated
max 0.84); the margin reached AUC 0.988 on the calibration set. RELATED at ≥ +0.02; ≤ −0.04
is only a "closer to leisure" hint that becomes `POSSIBLY_UNRELATED` after 3 minutes in front.
`tests/integration/test_relevance_verification.py` fails CI if the rules ever contradict a label.

## Session-level results

Seconds per scripted session. "none" is the engine before PR #40 (no relevance).

| Session (truth: on / off seconds) | Engine | false off-task | deviation estimated off-task | first flag after | on-task truth estimated ON_TASK |
| --- | --- | --- | --- | --- | --- |
| AR study: lecture, notes, LoL highlights (1380 / 300) | none | 0 | 0 | never | 1200 |
| | rules (+model) | 2 | 241 | 59 s | 1378 |
| DB exam: video, AI chat, notes, Netflix (1320 / 360) | none | 0 | 0 | never | 1320 |
| | rules (+model) | 2 | 301 | 59 s | 1318 |
| Coding: IDE, GitHub issues, music video (1380 / 240) | none | 0 | 0 | never | 1380 |
| | rules (+model) | 2 | 181 | 59 s | 1378 |
| Korean history: lecture, unmarked entertainment (600 / 420) | all | 0 | 0 | never | 600 |
| Passive lecture, camera off, no input (1200 / 0) | all | 0 | — | — | 1200 |
| **Total (5880 / 1320)** | none | 0 | 0 | | 5700 |
| | rules (+model) | **6** | **723** | | **5874** |

- The 6 false off-task seconds are all hysteresis: the 2 s it takes to return to `ON_TASK`
  after the user goes back to work (`enter_dwell_s` = 3 s), as for any other deviation.
- Notes right after a lecture count as work (+178 s in the AR session); before, they were
  `UNKNOWN` because Notepad is not on the lecture allow list.
- A detour is flagged after the 60 s grace period (`unrelated_page_s`), never sooner.
- The model adds nothing in these sessions because their titles were already decided by rules.
  "침착맨 삼국지 정주행" stays `UNCERTAIN` (margin −0.016, not below −0.04): unmarked
  entertainment is not flagged, by design.

## Latency and resources

| Measure | Result |
| --- | --- |
| Model verify (SHA256) + load | 1.04 s from source, 1.20 s in FocusLab.exe; on the analyzer thread, only after the feature is on and a title needs it |
| Inference per title | median 3.6 ms, p95 5.0 ms |
| Page change → model result | the next session tick (≤ 1 s); the tick itself never waits (`test_lookup_never_waits_for_a_slow_model_load`) |
| Memory | +186 MiB RSS once the model is loaded; nothing without it |
| 8 simulated hours, a page change every 30 s (960 changes, 600 distinct titles) | 4.8 s CPU in total (5.0 ms per page change, 0.17 ms per tick); RSS 227 → 231 MiB, peak 231; cache capped at 512 entries |

## Packaging and licenses

- `FocusLab.exe` built with `scripts/build_exe.py` (PyInstaller, on this machine, into a scratch
  folder) includes onnxruntime (+37 MB) and sentencepiece (+1 MB). In that build
  `FocusLab.exe --check` reported both modules and `FocusLab.exe --relevance-selftest` verified,
  loaded and ran the model with the same scores as the source run.
- The model is never bundled; it is downloaded only from Settings after confirmation, from the
  pinned upstream revision, and verified by SHA256 (see `THIRD_PARTY_NOTICES.md`).
- Licenses: model MIT (model card), onnxruntime MIT, sentencepiece Apache-2.0.
  `tokenizers` was rejected because it pulls in `huggingface-hub` and an HTTP client.

## Disable, removal and failure recovery

| Situation | Behavior | Test |
| --- | --- | --- |
| Model not installed / feature off | rules and context only | `test_engine_uses_the_model_only_where_rules_found_no_evidence`, scenarios |
| Download declined | nothing downloaded, feature stays off | `test_relevance_model_toggle_downloads_only_after_consent` |
| Tampered or cancelled download | file removed, error shown | `test_install_rejects_a_bad_checksum_and_leaves_nothing`, `test_install_can_be_cancelled` |
| Corrupt file on disk (right size, wrong content) | refused at load; analyzer `FAILED`; rules continue; Settings says "using rules only" | `test_a_corrupt_model_file_is_refused_and_the_rules_carry_on`, `test_settings_say_when_the_model_could_not_load` |
| Turned off or removed mid-session | analyzer closed; the session keeps estimating | `test_turning_the_model_off_or_removing_it_mid_session_keeps_the_session_running` |
| Relevance engine raises | logged; the session continues without relevance | `test_a_failing_relevance_engine_never_stops_the_session` |
| Runtime missing in a build | `--relevance-selftest` exits 1; Settings shows "Unavailable in this build" | `test_relevance_selftest_without_a_usable_model` |

## Privacy checks

- Titles reach relevance only with the existing, separate page-title consent; withdrawing it
  stops title use on the next tick and drops cached titles, vectors and the current answer
  (`test_withdrawing_title_consent_stops_title_use_on_the_next_tick`,
  `test_forgetting_titles_discards_cached_and_in_flight_results`).
- A whole session with titles and a one-time answer writes no title text to the database; only
  "Also use for similar goals" stores one, and withdrawing title consent deletes it
  (`test_page_titles_are_never_written_unless_the_user_keeps_a_rule`).
- No network access except the confirmed model download.

## Limitations and open items

- **Synthetic data only.** No real-usage accuracy exists yet; adding user corrections to the
  evaluation needs a separate, explicit consent flow (not built).
- The calibration set is small (90 titles); thresholds may need adjustment on real titles.
- **BGE-M3 was not compared.** Its ONNX export is about 2.2 GB, unsuitable as an on-device
  default; the comparison planned as an accuracy reference is still open.
- The model was measured on one fast CPU; slower laptops will be slower per title (still off
  the session thread).
- Manual checks on Windows with real Chrome/Edge pages are pending (see each PR).
- A one-off failure of two parrot-animation GUI tests (`tests/e2e/test_mascot_flight.py`) was
  seen once in a full local run and not reproduced in three further runs; unrelated code.

# Third-party dependencies and assets

Apache-2.0 applies to original FocusLab code; it does not relicense dependencies, models or trademarks.
Exact versions are pinned in `uv.lock`. This table records the licenses as declared by each project
and must be re-verified before each binary release.

## Runtime dependencies (declared in pyproject.toml)

| Component | Locked version | Declared license | Notes |
| --- | --- | --- | --- |
| PySide6 / Qt for Python | 6.10.3 | LGPLv3 / GPLv3 / commercial | Used as unmodified dynamic libraries. Binary distribution must preserve LGPL relinking rights and ship Qt notices. |
| OpenCV (`opencv-contrib-python`) | 5.0.0.93 | Apache-2.0 | Also required by MediaPipe; wheels bundle FFmpeg and other third-party notices that must be carried along. |
| MediaPipe | 0.10.35 | Apache-2.0 | Pulls matplotlib (PSF-style), sounddevice (MIT), absl-py, flatbuffers (Apache-2.0). |
| NumPy | 2.4.6 | BSD-3-Clause | |
| psutil | 7.2.2 | BSD-3-Clause | |
| pywin32 | 312 | PSF-2.0 | Windows only. |
| ONNX Runtime (`onnxruntime`) | 1.31.0 | MIT | CPU inference for the optional relevance model; imported only when that feature is on. |
| SentencePiece (`sentencepiece`) | 0.2.2 | Apache-2.0 | Tokenizer for the optional relevance model; no further dependencies. |

Development-only: pytest (MIT), pytest-qt (MIT), ruff (MIT), hatchling (MIT).

## Bundled UI font

Pretendard Variable v1.3.9 by Kil Hyung-jin is bundled in `src/focuslab/ui/fonts/`.
Source: https://github.com/orioncactus/pretendard/tree/v1.3.9
License: SIL Open Font License 1.1; the original notice is included as `fonts/OFL.txt`.
The font is loaded locally and does not require a system installation or network access.

## Model assets (not committed to the repository)

| Asset | Source | SHA256 | License status |
| --- | --- | --- | --- |
| `face_landmarker.task` (float16, v1) | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | Published by Google MediaPipe; the model card lists Apache-2.0. Confirm redistribution terms before bundling it in an installer. |

| `multilingual-e5-small-qint8.onnx` (= upstream `onnx/model_qint8_avx512_vnni.onnx`) | `https://huggingface.co/intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3` | `dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88` | MIT (model card). Optional task-relevance model, 118 MB. |
| `sentencepiece.bpe.model` | same repository and revision, `onnx/sentencepiece.bpe.model` | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` | MIT (model card). Tokenizer of the model above. |

The face model is downloaded only when the user runs `focuslab --fetch-models` (or the settings
button) and is verified against the SHA256 above. `assets/models/*.task` is git-ignored.
The relevance model is downloaded only after the user turns on "Task relevance AI" in Settings
and confirms; it is verified against the SHA256 values above, never bundled in the EXE, and
`assets/models/relevance/` is git-ignored. Settings → "Remove model" deletes it.

## Activity tracking engine and browser extension

- The activity recorder, classifier, automatic sessions, dashboard, native messaging host and the
  `browser_extension/` MV3 extension are original FocusLab code (Apache-2.0). They add **no new
  runtime dependencies**: Windows APIs are called through the Python standard library (`ctypes`,
  `winreg`) and the already-listed pywin32/psutil. The extension uses only the Chrome extension APIs.
- ActivityWatch was used only as a reference for publicly documented product features (activity
  timeline, AFK detection, browser watcher). No ActivityWatch source code, schemas or assets are
  copied, and FocusLab neither requires nor talks to an ActivityWatch installation.
- Development-only: Node.js (`node --test`) runs the extension tests; no npm packages are installed.

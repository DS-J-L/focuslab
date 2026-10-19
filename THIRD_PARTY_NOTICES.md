# Third-party dependencies and assets

Apache-2.0 applies to original FocusLab code; it does not relicense dependencies, models or trademarks.
Exact versions are pinned in `uv.lock`. This table records the licenses as declared by each project
and must be re-verified before shipping binaries (PR-13).

## Runtime dependencies (declared in pyproject.toml)

| Component | Locked version | Declared license | Notes |
| --- | --- | --- | --- |
| PySide6 / Qt for Python | 6.10.3 | LGPLv3 / GPLv3 / commercial | Used as unmodified dynamic libraries. Binary distribution must preserve LGPL relinking rights and ship Qt notices. |
| OpenCV (`opencv-contrib-python`) | 5.0.0.93 | Apache-2.0 | Also required by MediaPipe; wheels bundle FFmpeg and other third-party notices that must be carried along. |
| MediaPipe | 0.10.35 | Apache-2.0 | Pulls matplotlib (PSF-style), sounddevice (MIT), absl-py, flatbuffers (Apache-2.0). |
| NumPy | 2.4.6 | BSD-3-Clause | |
| psutil | 7.2.2 | BSD-3-Clause | |
| pywin32 | 312 | PSF-2.0 | Windows only. |

Development-only: pytest (MIT), pytest-qt (MIT), ruff (MIT), hatchling (MIT).

## Model assets (not committed to the repository)

| Asset | Source | SHA256 | License status |
| --- | --- | --- | --- |
| `face_landmarker.task` (float16, v1) | `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | Published by Google MediaPipe; the model card lists Apache-2.0. Confirm redistribution terms before bundling it in an installer. |

The model is downloaded only when the user runs `focuslab --fetch-models` (or the settings button)
and is verified against the SHA256 above. `assets/models/*.task` is git-ignored.

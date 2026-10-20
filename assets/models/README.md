# Models

Model files are not committed. This command downloads the model from the official MediaPipe repository, verifies its SHA256, and stores it in this folder:

```powershell
uv run focuslab --fetch-models
```

| File | Purpose | Source and checksum |
| --- | --- | --- |
| `face_landmarker.task` | Face presence and head pose (MediaPipe FaceLandmarker) | [Third-party notices](../../THIRD_PARTY_NOTICES.md) |

Before adding a model, verify its license and redistribution rights, then record its source, version, and SHA256 in `THIRD_PARTY_NOTICES.md`.

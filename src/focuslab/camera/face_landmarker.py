"""MediaPipe Tasks FaceLandmarker adapter (VIDEO mode, one face, on-device)."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class FaceResult:
    landmarks_xy: np.ndarray  # (N, 2) normalized image coordinates, kept in memory only
    matrix: np.ndarray | None  # 4x4 facial transformation matrix


class FaceLandmarkerAdapter:
    """Create and use on a single worker thread; call ``close`` from the same thread."""

    def __init__(self, model_path: Path) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        options = vision.FaceLandmarkerOptions(
            # Reading bytes avoids native path issues with non-ASCII Windows user folders.
            base_options=BaseOptions(model_asset_buffer=Path(model_path).read_bytes()),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> FaceResult | None:
        import cv2
        import mediapipe as mp

        ts = max(timestamp_ms, self._last_ts + 1)  # VIDEO mode needs increasing timestamps
        self._last_ts = ts
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts)
        if not result.face_landmarks:
            return None
        points = np.array([(p.x, p.y) for p in result.face_landmarks[0]], dtype=np.float32)
        matrices = result.facial_transformation_matrixes
        return FaceResult(points, np.asarray(matrices[0]) if matrices else None)

    def close(self) -> None:
        self._landmarker.close()

"""Head direction and observation quality from FaceLandmarker outputs. No identity features."""

import math

import numpy as np


def euler_from_matrix(matrix: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from MediaPipe's facial transformation matrix.

    The canonical face looks down -Z in camera space; a positive rotation about X
    tilts the face downward, so pitch is negated to make positive mean "looking up".
    Per-user calibration still confirms the down direction.
    """
    rot = np.asarray(matrix, dtype=float)[:3, :3]
    rot = rot / np.linalg.norm(rot, axis=0)  # remove scale
    sy = math.hypot(rot[0, 0], rot[1, 0])
    rx = math.degrees(math.atan2(rot[2, 1], rot[2, 2]))
    ry = math.degrees(math.atan2(-rot[2, 0], sy))
    rz = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
    return ry, -rx, rz


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def brightness_quality(gray_mean: float) -> float:
    """0 for a dark/covered camera, 1 for a normally lit frame."""
    return _clamp01((gray_mean - 30) / 50)


def face_quality(landmarks_xy: np.ndarray, gray_mean: float) -> float:
    """Heuristic 0..1: face inside the frame, large enough, and lit well enough."""
    xs, ys = landmarks_xy[:, 0], landmarks_xy[:, 1]
    inside = float(np.mean((xs >= 0) & (xs <= 1) & (ys >= 0) & (ys <= 1)))
    width = float(np.clip(xs, 0, 1).max() - np.clip(xs, 0, 1).min())
    size = _clamp01(width / 0.15)
    return inside * size * brightness_quality(gray_mean)

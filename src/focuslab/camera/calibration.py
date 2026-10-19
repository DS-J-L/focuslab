"""Per-user head pose calibration: forward pose offset and on-screen angle limits.

The user looks at the screen centre, the left and right screen edges, and the
keyboard/desk. Looking at a screen edge still counts as on-screen, so the yaw
limit sits beyond the measured edges.
"""

import json
from dataclasses import asdict, dataclass
from statistics import median

from focuslab.domain.models import HeadDirection

Pose = tuple[float, float]  # (yaw_deg, pitch_deg) as produced by head_pose


@dataclass(frozen=True)
class Calibration:
    yaw_offset: float = 0.0
    pitch_offset: float = 0.0
    pitch_sign: float = 1.0
    yaw_limit: float = 25.0
    down_limit: float = 20.0
    up_limit: float = 20.0
    calibrated: bool = False

    def relative(self, yaw: float, pitch: float) -> Pose:
        """Angles relative to the forward pose; negative pitch always means looking down."""
        return yaw - self.yaw_offset, (pitch - self.pitch_offset) * self.pitch_sign

    def classify(self, yaw: float, pitch: float) -> HeadDirection:
        """Classify relative angles. Looking down is reported separately, never as AWAY."""
        if abs(yaw) > self.yaw_limit or pitch > self.up_limit:
            return HeadDirection.AWAY
        if pitch < -self.down_limit:
            return HeadDirection.DOWN
        return HeadDirection.FORWARD

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str | None) -> "Calibration":
        if not text:
            return cls()
        try:
            return cls(**json.loads(text))
        except (TypeError, ValueError):
            return cls()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calibrate(
    forward: list[Pose], left: list[Pose], right: list[Pose], down: list[Pose]
) -> Calibration:
    """Build a calibration from raw pose samples for each step. Raises if a step is empty."""
    if not (forward and left and right and down):
        raise ValueError("every calibration step needs at least one face sample")
    yaw0 = median(p[0] for p in forward)
    pitch0 = median(p[1] for p in forward)
    edge = max(abs(median(p[0] for p in left) - yaw0), abs(median(p[0] for p in right) - yaw0))
    down_delta = median(p[1] for p in down) - pitch0
    defaults = Calibration()
    if abs(down_delta) < 5:  # down step barely moved; keep the default pitch handling
        sign, down_limit = 1.0, defaults.down_limit
    else:
        sign = -1.0 if down_delta > 0 else 1.0
        down_limit = _clamp(abs(down_delta) * 0.6, 8, 40)
    return Calibration(
        yaw_offset=yaw0,
        pitch_offset=pitch0,
        pitch_sign=sign,
        yaw_limit=_clamp(edge * 1.2 + 5, 12, 45),
        down_limit=down_limit,
        up_limit=defaults.up_limit,
        calibrated=True,
    )

"""Local hover strokes: a pass, pointer jitter or a horizontal sweep is not a pet."""

import math

STROKE_PX = 12.0  # logical pixels; independent of display scaling and mouse polling rate
MAX_GAP_S = .85
MIN_LEG_S = .08


class PettingGesture:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last: tuple[float, float, float] | None = None
        self._anchor = self._peak = (0.0, 0.0)
        self._direction = 0
        self._turns = 0
        self._leg_at = 0.0

    def move(self, x: float, y: float, now: float) -> bool:
        """True at deliberate reversals, after at least two vertical direction changes."""
        previous = self._last
        if (previous is None or now - previous[2] > MAX_GAP_S or now < previous[2]
                or math.hypot(x - previous[0], y - previous[1]) > 80):
            self.reset()
            self._anchor = self._peak = (x, y)
            self._leg_at = now
        self._last = (x, y, now)
        travel = y - self._anchor[1]
        if abs(x - self._anchor[0]) > max(14, abs(travel) * .8):
            self.reset()
            return False
        if not self._direction:
            if abs(travel) >= STROKE_PX:
                self._direction = 1 if travel > 0 else -1
                self._peak = (x, y)
            return False
        if (y - self._peak[1]) * self._direction >= 0:
            self._peak = (x, y)
            return False
        if abs(y - self._peak[1]) < STROKE_PX:
            return False  # hysteresis: tiny reversals near the tip are only jitter
        if now - self._leg_at < MIN_LEG_S:
            self.reset()
            return False
        self._direction *= -1
        self._anchor, self._peak = self._peak, (x, y)
        self._leg_at = now
        self._turns += 1
        return self._turns >= 2

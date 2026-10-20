"Poses: every value the renderer needs to draw one parrot, and blending between them."

import math
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Pose:
    """One parrot at one instant. Neutral values draw a calm parrot sitting on the branch."""

    x: float = 0.0  # px, relative to its seat on the branch (feet)
    y: float = 0.0  # px, negative is up
    tilt: float = 0.0  # degrees, whole body around the feet; positive leans right
    squash: float = 1.0  # >1 stretches up, <1 squats
    scale: float = 1.0
    puff: float = 0.0  # 0..1 fluffed-up feathers (angry, cold)
    turn: float = 0.0  # -1..1 face turned left/right
    head_tilt: float = 0.0  # degrees
    look_x: float = 0.0  # -1..1 pupils
    look_y: float = 0.0  # -1..1, negative looks up
    eye_open: float = 1.0  # 0 closed .. 1 open
    beak_open: float = 0.0  # 0..1
    wing_l: float = 0.0  # degrees raised away from the body
    wing_r: float = 0.0
    crest: float = 0.0  # degrees the head feathers sway
    blush: float = 0.0  # 0..1 extra cheek colour
    airborne: float = 0.0  # 0 perched .. 1 flying (feet tucked)
    alpha: float = 1.0
    eyes: str = "normal"  # normal | happy | angry | wide
    emote: str | None = None  # zzz | note | alert | anger | dots | heart | sparkle
    emote_t: float = 0.0  # seconds the emote has been shown, for its own small motion


NUMERIC = tuple(f.name for f in fields(Pose) if f.type is float and f.name != "emote_t")
NEUTRAL = Pose()


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def blend(a: Pose, b: Pose, t: float) -> Pose:
    """``a`` at 0, ``b`` at 1. Discrete values (eyes, emote) switch halfway."""
    if t <= 0:
        return a
    if t >= 1:
        return b
    values = {name: lerp(getattr(a, name), getattr(b, name), t) for name in NUMERIC}
    return replace(b if t >= 0.5 else a, **values)


def approach(current: float, target: float, dt: float, time_constant: float) -> float:
    """Frame-rate independent exponential smoothing towards ``target``."""
    if time_constant <= 0:
        return target
    return target + (current - target) * math.exp(-max(0.0, dt) / time_constant)

"Poses (every value the renderer needs for one parrot), blending, and data-driven behaviors."

import json
import math
from dataclasses import dataclass, field, fields, replace
from functools import cache
from importlib.resources import files


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


# Behaviors ------------------------------------------------------------------------------
DISCRETE = ("eyes",)
FADE = 0.12  # waves fade in and out over this share of a behavior


@dataclass(frozen=True)
class Behavior:
    """A short animation described in ``animations.json``; adding one needs no code."""

    name: str
    duration: float
    tracks: dict[str, tuple[tuple[float, float | str], ...]]
    waves: dict[str, tuple[float, float, float]]  # channel: (amplitude, Hz, offset)
    emotes: tuple[tuple[float, str | None], ...] = ()
    weight: dict[str, float] = field(default_factory=dict)
    cooldown: float = 0.0
    audience: bool = False  # the others may turn to watch
    pair: bool = False  # played together with a neighbour, each aimed at the other
    mirror: frozenset[str] = frozenset()  # channels that flip when aimed at the left
    random: bool = True  # False: only played on purpose (moods, flight)
    loop: bool = False

    def sample(self, t: float, side: int = 1, base: Pose = NEUTRAL) -> Pose:
        """The pose ``t`` seconds in; ``side`` is -1 when aimed at the left neighbour."""
        u = (t / self.duration) % 1.0 if self.loop else min(1.0, max(0.0, t / self.duration))
        values: dict[str, float | str] = {}
        for channel, keys in self.tracks.items():
            values[channel] = _sample_keys(keys, u, channel in DISCRETE)
        envelope = 1.0 if self.loop else min(1.0, u / FADE, (1 - u) / FADE)
        for channel, (amplitude, hz, offset) in self.waves.items():
            wave = offset + amplitude * math.sin(math.tau * hz * t)
            values[channel] = values.get(channel, getattr(base, channel)) + envelope * wave
        for channel in self.mirror & values.keys():
            if channel not in DISCRETE:
                values[channel] = side * values[channel]
        emote, since = base.emote, base.emote_t
        for at, name in self.emotes:
            if u >= at:
                emote, since = name, t - at * self.duration
        return replace(base, **values, emote=emote, emote_t=since)


def _sample_keys(keys, u: float, discrete: bool):
    if discrete:
        value = keys[0][1]
        for at, v in keys:
            if u >= at:
                value = v
        return value
    if u <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:], strict=False):
        if u <= t1:
            return lerp(v0, v1, ease_in_out((u - t0) / (t1 - t0)) if t1 > t0 else 1.0)
    return keys[-1][1]


def parse_behaviors(data: dict) -> dict[str, Behavior]:
    """Validate and build behaviors, so a typo in the data fails loudly in tests."""
    channels = {f.name for f in fields(Pose)} - {"emote", "emote_t"}
    behaviors = {}
    for name, spec in data["behaviors"].items():
        tracks = {
            k: tuple((float(t), v) for t, v in keys) for k, keys in spec.get("tracks", {}).items()
        }
        waves = {k: tuple(float(x) for x in v) for k, v in spec.get("waves", {}).items()}
        unknown = (tracks.keys() | waves.keys() | set(spec.get("mirror", ()))) - channels
        if unknown:
            raise ValueError(f"{name}: unknown pose channels {sorted(unknown)}")
        for channel, keys in tracks.items():
            times = [t for t, _ in keys]
            if not keys or times != sorted(times) or not 0 <= times[0] <= times[-1] <= 1:
                raise ValueError(f"{name}.{channel}: key times must rise within 0..1")
        if float(spec["duration"]) <= 0:
            raise ValueError(f"{name}: duration must be positive")
        behaviors[name] = Behavior(
            name=name,
            duration=float(spec["duration"]),
            tracks=tracks,
            waves=waves,
            emotes=tuple((float(t), e) for t, e in spec.get("emotes", ())),
            weight={k: float(v) for k, v in spec.get("weight", {}).items()},
            cooldown=float(spec.get("cooldown", 0)),
            audience=bool(spec.get("audience", False)),
            pair=bool(spec.get("pair", False)),
            mirror=frozenset(spec.get("mirror", ())),
            random=bool(spec.get("random", True)),
            loop=bool(spec.get("loop", False)),
        )
    return behaviors


@cache
def load_behaviors() -> dict[str, Behavior]:
    text = files("focuslab.ui.mascot").joinpath("animations.json").read_text("utf-8")
    return parse_behaviors(json.loads(text))

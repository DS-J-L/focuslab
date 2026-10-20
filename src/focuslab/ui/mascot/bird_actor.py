"One parrot: the behavior it is playing, breathing, blinking, and reactions to the pointer."

import math
import random
from dataclasses import dataclass, replace

from focuslab.ui.mascot.animation import NEUTRAL, Behavior, Pose, approach, blend
from focuslab.ui.mascot.renderer import Plumage

BLINK_S = 0.14
HOVER_S = 0.12  # time constant for perking up and settling down


@dataclass(frozen=True)
class Attention:
    """Where a parrot's attention is. ``toward`` is -1 (left) .. 1 (right)."""

    hovered: bool = False  # the pointer is on this parrot
    toward: float = 0.0  # glance sideways at something
    up: bool = False  # look up (at the window buttons)
    emote: str | None = None


CALM = Attention()


class BirdActor:
    def __init__(self, name: str, plumage: Plumage, rng: random.Random) -> None:
        self.name = name
        self.plumage = plumage
        self.rng = rng
        self.attention = CALM
        self._phase = rng.uniform(0, math.tau)  # so the three never breathe in step
        self._next_blink: float | None = None
        self._last: float | None = None
        self._perk = 0.0  # smoothed 0..1 hover amount
        self._glance = 0.0  # smoothed toward
        self._up = 0.0
        self._emote_since = 0.0
        self.behavior: Behavior | None = None
        self._started = 0.0
        self._side = 1
        self._watch = 0.0  # direction of a neighbour being watched, until _watch_until
        self._watch_until = 0.0

    # behaviors ----------------------------------------------------------------------
    def play(self, behavior: Behavior, now: float, side: int = 1) -> None:
        self.behavior, self._started, self._side = behavior, now, side

    def stop(self) -> None:
        self.behavior = None

    def busy(self, now: float) -> bool:
        b = self.behavior
        if b is not None and not b.loop and now - self._started >= b.duration:
            self.behavior = None
        return self.behavior is not None

    def watch(self, toward: float, until: float) -> None:
        "Turn to look at a neighbour doing something (``toward`` -1 left, 1 right)."
        self._watch, self._watch_until = toward, until

    def attend(self, attention: Attention, now: float) -> None:
        if attention.emote != self.attention.emote:
            self._emote_since = now
        self.attention = attention

    def pose(self, now: float) -> Pose:
        dt = 0.0 if self._last is None else now - self._last
        self._last = now
        base = NEUTRAL
        if self.busy(now):
            base = self.behavior.sample(now - self._started, self._side)
        a = self.attention
        toward = a.toward
        if a == CALM and now < self._watch_until:
            toward = self._watch
        self._perk = approach(self._perk, 1.0 if a.hovered else 0.0, dt, HOVER_S)
        self._glance = approach(self._glance, toward, dt, HOVER_S * 2.5)
        self._up = approach(self._up, 1.0 if a.up else 0.0, dt, HOVER_S * 1.5)

        breath = math.sin(now * math.tau / 3.4 + self._phase)
        pose = replace(
            base,
            squash=base.squash * (1 + 0.022 * breath),
            crest=base.crest + 3 * math.sin(now * math.tau / 5.0 + self._phase),
            eye_open=base.eye_open * self._blink(now),
        )
        if self._glance or self._up:
            pose = replace(
                pose,
                turn=pose.turn + 0.7 * self._glance,
                look_x=max(-1.0, min(1.0, pose.look_x + self._glance + 0.4 * self._up)),
                look_y=pose.look_y - self._up,
                tilt=pose.tilt + 4 * self._glance,
            )
        if self._perk > 0.01:
            perked = replace(
                pose,
                y=pose.y - 4,
                scale=pose.scale * 1.08,
                eyes="wide",
                eye_open=max(pose.eye_open, 1.0),
                wing_l=pose.wing_l + 18,
                wing_r=pose.wing_r + 18,
                crest=pose.crest + 8,
            )
            pose = blend(pose, perked, self._perk)
        if a.emote:
            pose = replace(pose, emote=a.emote, emote_t=now - self._emote_since)
        return pose

    def _blink(self, now: float) -> float:
        if self._next_blink is None:
            self._next_blink = now + self.rng.uniform(0.8, 4.0)
        if now < self._next_blink:
            return 1.0
        t = now - self._next_blink
        if t >= BLINK_S:
            # Now and then a quick double blink.
            gap = 0.25 if self.rng.random() < 0.15 else self.rng.uniform(2.5, 6.0)
            self._next_blink = now + gap
            return 1.0
        return abs(math.cos(math.pi * t / BLINK_S))

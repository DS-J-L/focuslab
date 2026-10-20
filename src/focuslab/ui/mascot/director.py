"""Coordinates the three parrots: who does what and when, and how they react to each other.

Each parrot picks its next behavior on its own, weighted by its personality (red dozes and
startles, blue stares and preens, yellow sings and dances). When one performs, the others
may turn to watch; now and then two neighbours lean on each other. Per-behavior cooldowns
and a shared cooldown for interactions keep it from getting busy.

A mood (from the behavior policy) replaces the idle behaviors with a looping reaction:
watching you, scolding, sleeping through a pause, or waiting while you are away.
"""

import random
from dataclasses import dataclass, replace

from focuslab.ui.mascot.animation import Behavior, Pose, load_behaviors
from focuslab.ui.mascot.behavior_policy import Mood
from focuslab.ui.mascot.bird_actor import CALM, Attention, BirdActor
from focuslab.ui.mascot.renderer import BLUE, RED, YELLOW

# Left to right on the branch, matching the session action each parrot stands for.
PAUSE, FINISH, BREAK = range(3)
WINDOW = "window"  # the pointer is on the minimize / close buttons


@dataclass(frozen=True)
class Motion:
    gap: tuple[float, float] | None  # seconds of rest between behaviors; None: none at all
    watch: float  # chance that the others watch a performance
    interaction_cooldown: float  # between pair behaviors and watching


MOTION = {
    "minimal": Motion(None, 0.0, 0.0),  # breathing and blinking only
    "normal": Motion((7.0, 18.0), 0.45, 30.0),
    "lively": Motion((3.0, 9.0), 0.8, 12.0),
}
DEFAULT_MOTION = "normal"

# Looping reaction per parrot (red, blue, yellow) for each mood that has one.
MOOD_LOOPS = {
    Mood.WATCH: ("watch_alert", "watch", "watch"),
    Mood.WARN: ("scold", "scold", "scold"),
    Mood.ALARM: ("angry", "scold", "angry"),
    Mood.PAUSED: ("sleep", "sleep", "sleep"),
    Mood.AWAY: ("wait", "wait", "wait"),
}
LOOP_STAGGER_S = 0.37  # so the three never move in step


class Director:
    def __init__(
        self,
        rng: random.Random | None = None,
        behaviors: dict[str, Behavior] | None = None,
        motion: str = DEFAULT_MOTION,
    ) -> None:
        self.rng = rng or random.Random()
        self.behaviors = load_behaviors() if behaviors is None else behaviors
        self.actors = (
            BirdActor("red", RED, self.rng),
            BirdActor("blue", BLUE, self.rng),
            BirdActor("yellow", YELLOW, self.rng),
        )
        self.hover: int | str | None = None
        self.mood = Mood.CALM
        self.away: set[int] = set()  # flying around the screen; their seat is empty
        self.motion = MOTION[DEFAULT_MOTION]
        self.set_motion(motion)
        self._next: list[float | None] = [None] * len(self.actors)
        self._cooldown: dict[tuple[int, str], float] = {}
        self._interaction_at = 0.0

    def set_motion(self, level: str) -> None:
        motion = MOTION.get(level, MOTION[DEFAULT_MOTION])
        if motion != self.motion:
            self.motion = motion
            for actor in self.actors:  # restart, moving or still
                actor.stop()

    @property
    def still(self) -> bool:
        "Minimal movement: reactions show as expressions without motion."
        return self.motion.gap is None

    def set_mood(self, mood: Mood, now: float) -> None:
        if mood == self.mood:
            return
        if mood in MOOD_LOOPS or self.mood in MOOD_LOOPS:
            for actor in self.actors:
                actor.stop()
        self.mood = mood
        gap = self.motion.gap or (0.0, 0.0)
        rest = self.rng.uniform(*gap) if gap[1] else 0.0
        self._next = [now + rest] * len(self.actors)
        if self.still:
            return
        if mood is Mood.CHEER:
            cheer = self.behaviors["cheer"]
            for i, actor in enumerate(self.actors):
                actor.play(cheer, now + i * 0.12)
            self._next = [now + cheer.duration + rest] * len(self.actors)
        elif mood is Mood.BREAK:  # yellow, the break parrot, starts singing
            self.actors[BREAK].play(self.behaviors["sing"], now)

    def set_hover(self, target: int | str | None, now: float) -> None:
        """The pointer moved onto a parrot (its index), the window buttons, or away."""
        self.hover = target
        for i, actor in enumerate(self.actors):
            if target == WINDOW:
                # Everyone peeks at the buttons; the one closest says "...".
                attention = Attention(up=True, toward=1.0, emote="dots" if i == BREAK else None)
            elif isinstance(target, int):
                if i == target:
                    attention = Attention(hovered=True)
                    actor.stop()  # whatever it was doing, it pays attention now
                else:  # the others glance at the parrot being pointed at
                    attention = Attention(toward=1.0 if target > i else -1.0)
            else:
                attention = CALM
            actor.attend(attention, now)

    def set_away(self, i: int, away: bool, now: float) -> None:
        "Parrot ``i`` left the branch to fly around, or came back and lands."
        actor = self.actors[i]
        actor.stop()
        if away:
            self.away.add(i)
        elif i in self.away:
            self.away.discard(i)
            actor.play(self.behaviors["land"], now)

    def poses(self, now: float) -> list[Pose]:
        self._schedule(now)
        poses = [actor.pose(now) for actor in self.actors]
        return [replace(p, alpha=0.0) if i in self.away else p for i, p in enumerate(poses)]

    def _idle(self, i: int, now: float) -> bool:
        return i not in self.away and self.hover != i and not self.actors[i].busy(now)

    # scheduling ---------------------------------------------------------------------
    def _schedule(self, now: float) -> None:
        loops = MOOD_LOOPS.get(self.mood)
        if loops:
            for i, actor in enumerate(self.actors):
                if self._idle(i, now):
                    behavior = self.behaviors[loops[i]]
                    actor.play(behavior, now - i * LOOP_STAGGER_S, still=self.still)
            return
        gap = self.motion.gap
        if gap is None:
            return
        for i in range(len(self.actors)):
            if self._next[i] is None:  # stagger the first behaviors
                self._next[i] = now + self.rng.uniform(gap[0] * 0.3, gap[1])
            if not self._idle(i, now) or now < self._next[i]:
                continue
            behavior = self._pick(i, now)
            if behavior is None:
                self._next[i] = now + self.rng.uniform(*gap)
                continue
            self._start(i, behavior, now)

    def _pick(self, i: int, now: float) -> Behavior | None:
        name = self.actors[i].name
        options = []
        for b in self.behaviors.values():
            weight = b.weight.get(name, 0.0)
            if not b.random or weight <= 0 or now < self._cooldown.get((i, b.name), 0.0):
                continue
            if b.pair and (now < self._interaction_at or not self._partners(i, b, now)):
                continue
            options.append((b, weight))
        if not options:
            return None
        return self.rng.choices([b for b, _ in options], [w for _, w in options])[0]

    def _partners(self, i: int, behavior: Behavior, now: float) -> list[int]:
        "Idle neighbours that may join ``behavior`` (its cooldown applies to them too)."
        return [
            j
            for j in (i - 1, i + 1)
            if 0 <= j < len(self.actors)
            and self._idle(j, now)
            and now >= self._cooldown.get((j, behavior.name), 0.0)
        ]

    def _start(self, i: int, behavior: Behavior, now: float) -> None:
        gap = self.motion.gap
        cast = [i]
        if behavior.pair:
            j = self.rng.choice(self._partners(i, behavior, now))
            cast.append(j)
            side = 1 if j > i else -1
            self.actors[i].play(behavior, now, side)
            self.actors[j].play(behavior, now, -side)
            self._interaction_at = now + self.motion.interaction_cooldown
        else:
            self.actors[i].play(behavior, now)
            if (
                behavior.audience
                and now >= self._interaction_at
                and self.rng.random() < self.motion.watch
            ):
                for j, other in enumerate(self.actors):
                    if j != i and self._idle(j, now):
                        other.watch(1.0 if i > j else -1.0, now + behavior.duration * 0.7)
                self._interaction_at = now + self.motion.interaction_cooldown
        for k in cast:
            self._cooldown[(k, behavior.name)] = now + behavior.cooldown
            self._next[k] = now + behavior.duration + self.rng.uniform(*gap)

"Coordinates the three parrots: who reacts to what, and how they react to each other."

import random

from focuslab.ui.mascot.animation import Pose
from focuslab.ui.mascot.bird_actor import CALM, Attention, BirdActor
from focuslab.ui.mascot.renderer import BLUE, RED, YELLOW

# Left to right on the branch, matching the session action each parrot stands for.
PAUSE, FINISH, BREAK = range(3)
WINDOW = "window"  # the pointer is on the minimize / close buttons


class Director:
    def __init__(self, rng: random.Random | None = None) -> None:
        rng = rng or random.Random()
        self.actors = (
            BirdActor("red", RED, rng),
            BirdActor("blue", BLUE, rng),
            BirdActor("yellow", YELLOW, rng),
        )
        self.hover: int | str | None = None

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
                else:  # the others glance at the parrot being pointed at
                    attention = Attention(toward=1.0 if target > i else -1.0)
            else:
                attention = CALM
            actor.attend(attention, now)

    def poses(self, now: float) -> list[Pose]:
        return [actor.pose(now) for actor in self.actors]

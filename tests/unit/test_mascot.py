"""Parrot poses: blending, breathing and blinking, and reactions to the pointer."""

import random

from focuslab.ui.mascot.animation import Pose, blend
from focuslab.ui.mascot.director import BREAK, FINISH, PAUSE, WINDOW, Director


def frames(director, start, seconds, fps=30):
    t = start
    poses = []
    while t < start + seconds:
        poses.append(director.poses(t))
        t += 1 / fps
    return poses


def test_blend_interpolates_numbers_and_switches_discrete_values_halfway():
    a, b = Pose(), Pose(y=-10, eyes="happy", emote="note")
    assert blend(a, b, 0) == a and blend(a, b, 1) == b
    quarter = blend(a, b, 0.25)
    assert quarter.y == -2.5 and quarter.eyes == "normal" and quarter.emote is None
    assert blend(a, b, 0.75).eyes == "happy"


def test_parrots_breathe_out_of_step_and_blink_now_and_then():
    director = Director(random.Random(1))
    poses = frames(director, 0.0, 12)
    for i in range(3):
        squash = [p[i].squash for p in poses]
        assert max(squash) - min(squash) > 0.02  # breathing
        assert min(p[i].eye_open for p in poses) < 0.3  # blinked
        assert sum(p[i].eye_open >= 0.99 for p in poses) > len(poses) * 0.8  # mostly open
    first = [p[0].squash for p in poses[:30]]
    second = [p[1].squash for p in poses[:30]]
    assert first != second


def test_pointed_at_parrot_perks_up_and_the_others_look_at_it():
    director = Director(random.Random(2))
    director.set_hover(FINISH, 0.0)
    red, blue, yellow = frames(director, 0.0, 1)[-1]
    assert blue.scale > 1.05 and blue.eyes == "wide" and blue.y < 0
    assert red.turn > 0.5 and yellow.turn < -0.5  # both glance at the middle one

    director.set_hover(None, 1.0)
    calm = frames(director, 1.0, 1.5)[-1]
    assert all(abs(p.turn) < 0.05 and p.scale < 1.01 for p in calm)


def test_window_buttons_make_everyone_peek_and_the_nearest_one_wonder():
    director = Director(random.Random(3))
    director.set_hover(WINDOW, 0.0)
    poses = frames(director, 0.0, 1)[-1]
    assert all(p.look_y < -0.5 for p in poses)
    assert poses[BREAK].emote == "dots"
    assert poses[PAUSE].emote is None and poses[FINISH].emote is None

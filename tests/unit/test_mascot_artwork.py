"""Real packaged art, stable facial animation, fallback and time-based transitions."""

import random
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from focuslab.ui.mascot import artwork
from focuslab.ui.mascot.animation import Pose, load_behaviors
from focuslab.ui.mascot.bird_actor import BirdActor
from focuslab.ui.mascot.renderer import (
    BLUE,
    PENDANT_CENTER,
    RED,
    YELLOW,
    head_placement,
    paint_bird,
)


def render(plumage, pose=None):
    pose = pose or Pose()
    image = QImage(320, 360, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.translate(160, 300)
    painter.scale(1.5, 1.5)
    paint_bird(painter, pose, plumage)
    painter.end()
    return image


def pixels(image):
    return np.asarray(image.constBits()).reshape(image.height(), image.bytesPerLine()).copy()


def test_packaged_character_rigs_are_complete_and_fit_the_memory_budget(qapp):
    artwork.preload_artwork()
    rigs = [artwork.character_art(name) for name in artwork.CHARACTER_IDS]
    assert all(rig.fallback is None and len(rig.parts) == 9 for rig in rigs)
    assert all(len(rig.faces) == 2 and all(len(row) == 9 for row in rig.faces) for rig in rigs)
    assert rigs[0].crest is None and rigs[1].crest is not None and rigs[2].crest is not None
    assert sum(rig.decoded_bytes for rig in rigs) < 48 * 1024 * 1024


@pytest.mark.parametrize("plumage", (RED, BLUE, YELLOW))
def test_blink_changes_face_pixels_without_moving_feet_or_head_outline(qapp, plumage):
    normal = render(plumage)
    closed = render(plumage, Pose(eye_open=0))
    a, b = pixels(normal), pixels(closed)
    assert np.count_nonzero(a != b) > 20
    assert np.array_equal(a[278:306], b[278:306])  # toe contact and body stay still
    # Alpha boundaries outside the textured facial patches remain identical.
    assert np.array_equal(a[:, 3::4], b[:, 3::4])


@pytest.mark.parametrize("plumage", (RED, BLUE, YELLOW))
def test_deployed_art_has_room_for_crest_and_flying_wings(qapp, plumage):
    image = render(plumage, Pose(airborne=1, wing_l=100, wing_r=10, head_tilt=9))
    alpha = pixels(image)[:, 3::4]
    assert alpha.max() > 0
    assert not alpha[0].any() and not alpha[-1].any()
    assert not alpha[:, 0].any() and not alpha[:, -1].any()


def test_rendering_uses_preloaded_art_without_decoding_each_frame(qapp, monkeypatch):
    artwork.preload_artwork()
    def unexpected_decode(spec):
        raise AssertionError("Image decoded during paint")
    monkeypatch.setattr(artwork, "_sheet", unexpected_decode)
    for value in (0, .25, .5, .75, 1):
        for bird in (RED, BLUE, YELLOW):
            assert not render(bird, Pose(eye_open=value)).isNull()


def test_bad_atlas_falls_back_to_the_same_character_without_breaking_controls(qapp, monkeypatch):
    artwork.character_art.cache_clear()
    with monkeypatch.context() as patcher:
        def missing_sheet(spec):
            raise ValueError("checksum mismatch")
        patcher.setattr(artwork, "_sheet", missing_sheet)
        rig = artwork.character_art("sky-parrot")
        assert rig.fallback is not None
        assert not render(BLUE).isNull()
    artwork.character_art.cache_clear()


def test_blink_uses_elapsed_time_and_wakes_the_active_frame_rate():
    samples = []
    for fps in (30, 60):
        actor = BirdActor("red", RED, random.Random(1))
        actor._next_blink = 10.0
        for index in range(int(fps * .12)):
            actor.pose(9.9 + index / fps)
        pose = actor.pose(10.078)
        assert not actor.resting and pose.eye_open == 0
        samples.append(actor.pose(10.14).eye_open)
    assert samples[0] == pytest.approx(samples[1])


def test_sleep_and_resume_connect_from_the_current_pose():
    actor = BirdActor("red", RED, random.Random(2))
    actor.pose(100)
    actor.play(load_behaviors()["sleep"], 100)
    beginning = actor.pose(100)
    midway = actor.pose(100.09)
    asleep = actor.pose(100.3)
    assert beginning.eye_open > midway.eye_open > asleep.eye_open
    actor.stop()
    beginning = actor.pose(100.3)
    assert beginning.eye_open == pytest.approx(asleep.eye_open)
    awake = actor.pose(100.6)
    assert awake.eye_open > .95


def test_future_staggered_gesture_does_not_start_before_its_time():
    actor = BirdActor("yellow", YELLOW, random.Random(3))
    actor.pose(10)
    actor.play(load_behaviors()["cheer"], 11)
    waiting = actor.pose(10.5)
    assert replace(waiting, squash=1, crest=0, eye_open=1) == Pose()


@pytest.mark.parametrize("plumage", (RED, BLUE, YELLOW))
def test_authored_head_directions_are_distinct_and_keep_the_toes_planted(qapp, plumage):
    directions = [Pose(turn=x, look_x=x) for x in (-1, -.5, 0, .5, 1)]
    directions += [Pose(look_y=-1), Pose(look_y=1)]
    images = [pixels(render(plumage, pose)) for pose in directions]
    assert len({im.tobytes() for im in images}) == 7
    assert all(np.array_equal(im[278:306], images[0][278:306]) for im in images)
    rig = artwork.character_art(plumage.character_id)
    assert rig.views and len(rig.views["yaw"]) == 5 and len(rig.views["pitch"]) == 4
    for bank in rig.views.values():
        for view in bank:
            alpha = [pixels(frame)[:, 3::4] for frame in view.frames]
            assert all(np.array_equal(alpha[0], a) for a in alpha[1:])
            assert len({pixels(frame).tobytes() for frame in view.frames}) == 3


@pytest.mark.parametrize("plumage", (RED, BLUE, YELLOW))
@pytest.mark.parametrize("behavior,side", (("preen", -1), ("preen", 1), ("preen_chest", 1)))
def test_preening_beak_follows_the_feather_through_each_stroke(qapp, plumage, behavior, side):
    rig = artwork.character_art(plumage.character_id)
    gesture = load_behaviors()[behavior]
    toes = pixels(render(plumage))[296:306]  # contact tips, below moving belly/wing feathers
    for u in (.3, .35, .5, .6, .7):
        pose = gesture.sample(gesture.duration * u, side)
        head = head_placement(rig, pose)
        assert head.contact is not None
        assert (head.transform.map(head.beak) - head.contact).manhattanLength() < .001
        if behavior == "preen_chest":
            delta = head.contact - PENDANT_CENTER
            assert delta.x() ** 2 + delta.y() ** 2 > 14 ** 2  # exposed feathers
        image = pixels(render(plumage, pose))
        assert np.array_equal(toes, image[296:306])
        assert not image[0, 3::4].any() and not image[-1, 3::4].any()


def test_idle_gazes_dwell_independently_and_yield_to_sleep_and_minimal_motion():
    from focuslab.ui.mascot.director import Director

    director = Director(random.Random(42), behaviors={})
    seen = [set() for _ in range(3)]
    series = [[] for _ in range(3)]
    for step in range(3600):
        for i, pose in enumerate(director.poses(step / 30)):
            series[i].append(round(pose.turn, 2))
            seen[i].add((round(pose.turn, 1), round(pose.look_y, 1)))
    assert all(len(directions) > 7 for directions in seen)
    assert series[0] != series[1] != series[2]
    # A dwell has a stable direction instead of constantly scanning left/right.
    assert any(len(set(series[0][i:i + 30])) == 1 for i in range(0, 3500, 30))
    actor = director.actors[0]
    actor.play(load_behaviors()["sleep"], 120)
    for step in range(61):
        pose = actor.pose(120 + step / 30)
    assert abs(pose.turn) < .01 and abs(pose.look_y) < .01
    director.set_motion("minimal")
    for step in range(1800):
        poses = director.poses(123 + step / 30)
        if step > 60:
            assert all(abs(p.turn) < .01 and abs(p.look_y) < .01 for p in poses)


def test_director_chooses_both_preening_sides_without_alternating_by_rule():
    from focuslab.ui.mascot.director import Director

    director = Director(random.Random(17))
    sides = []
    for step in range(20):
        director._start(1, director.behaviors["preen"], step * 60)
        sides.append(director.actors[1]._side)
    assert set(sides) == {-1, 1}
    assert any(a == b for a, b in zip(sides, sides[1:], strict=False))

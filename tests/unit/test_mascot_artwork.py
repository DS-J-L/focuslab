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
from focuslab.ui.mascot.renderer import BLUE, RED, YELLOW, paint_bird


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

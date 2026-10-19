"""Recorder wiring in the app: consent gates, demo mode, start/stop."""

import sys

import pytest

from focuslab.activity.recorder import RecorderState
from focuslab.domain.activity import ForegroundApp, ProbeSample
from focuslab.ui.context import AppContext


class FakeProbe:
    def sample(self) -> ProbeSample:
        return ProbeSample(ForegroundApp("code.exe", "Visual Studio Code"), 0.0)


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr("focuslab.ui.context.WindowsProbe", FakeProbe)
    created = []

    def make(demo=False):
        c = AppContext(demo)
        created.append(c)
        return c

    yield make
    for c in created:
        c.stop_recording()
        c.service.shutdown()


def test_demo_mode_never_records(ctx):
    c = ctx(demo=True)
    c.set_flag("consent.recording", True)
    assert c.start_recording() is False and c.recorder is None


def test_recording_requires_consent(ctx):
    c = ctx()
    assert c.start_recording() is False and c.recorder is None


@pytest.mark.skipif(sys.platform != "win32", reason="the recorder only runs on Windows")
def test_recording_starts_and_stops_with_consent(ctx):
    c = ctx()
    c.set_flag("consent.recording", True)
    assert c.start_recording() is True
    assert c.recorder.state is RecorderState.RUNNING
    c.recorder.tick()
    assert c.recorder.status().current.exe_name == "code.exe"
    c.stop_recording()
    assert c.recorder.state is RecorderState.STOPPED

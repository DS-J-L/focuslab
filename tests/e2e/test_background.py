"""Background behavior: onboarding consent, tray residency, recording pause, autostart entry."""

import sys

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QMessageBox

from focuslab import autostart
from focuslab.activity.recorder import RecorderState
from focuslab.domain.activity import ForegroundApp, ProbeSample
from focuslab.domain.models import CameraStatus, SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import MainWindow
from focuslab.ui.onboarding import OnboardingChoice, OnboardingDialog

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows recorder")


class FakeProbe:
    def __init__(self) -> None:
        self.calls = 0

    def sample(self) -> ProbeSample:
        self.calls += 1
        return ProbeSample(ForegroundApp("code.exe", "Visual Studio Code"), 0.0)


@pytest.fixture
def no_os(monkeypatch):
    monkeypatch.setattr("focuslab.ui.context.WindowsProbe", FakeProbe)
    monkeypatch.setattr("focuslab.ui.context.WindowsEventThread", None)
    monkeypatch.setattr(autostart, "enable", lambda *a, **k: "")
    monkeypatch.setattr(autostart, "disable", lambda *a, **k: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda *a, **k: False)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.fixture
def window(qtbot, no_os):
    ctx = AppContext(demo=False)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    yield win
    win.close_down()


def test_onboarding_defaults_collect_nothing(qtbot):
    dialog = OnboardingDialog()
    qtbot.addWidget(dialog)
    QTimer.singleShot(0, dialog.reject)
    dialog.exec()
    assert dialog.choice().recording is False and dialog.choice().autostart is False
    assert not dialog.recording.isChecked() and not dialog.autostart.isEnabled()


def test_onboarding_choice_requires_acceptance(qtbot):
    dialog = OnboardingDialog()
    qtbot.addWidget(dialog)
    dialog.recording.setChecked(True)
    dialog.autostart.setChecked(True)
    dialog.idle.setValue(10)
    dialog.done(QDialog.DialogCode.Accepted)
    assert dialog.choice() == OnboardingChoice(True, True, True, 10, "ko")
    dialog.done(QDialog.DialogCode.Rejected)
    assert dialog.choice().recording is False


def test_apply_onboarding_sets_consent_threshold_and_autostart(no_os, monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, "enable", lambda *a, **k: calls.append("on"))
    ctx = AppContext(demo=False)
    try:
        assert ctx.needs_onboarding
        ctx.apply_onboarding(OnboardingChoice(True, sys.platform == "win32", False, 7, "en"))
        assert not ctx.needs_onboarding and ctx.recording_consent
        assert ctx.idle_threshold_s == 420 and ctx.close_to_tray is False
        assert ctx.language == "en"
        assert calls == (["on"] if sys.platform == "win32" else [])
    finally:
        ctx.service.shutdown()


@windows_only
def test_closing_the_window_keeps_recording_in_the_tray(window, monkeypatch):
    ctx = window.ctx
    ctx.set_flag("consent.recording", True)
    assert ctx.start_recording()
    monkeypatch.setattr(window.tray, "isVisible", lambda: True)
    window.show()
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and not window.isVisible()
    assert ctx.recording_state is RecorderState.RUNNING


@windows_only
def test_tray_pause_persists_across_restart(window, no_os):
    ctx = window.ctx
    ctx.set_flag("consent.recording", True)
    ctx.start_recording()
    window.poll()
    assert window.tray.recording_action.text() == "기록 일시정지"
    window.toggle_recording_pause()
    assert ctx.recording_state is RecorderState.PAUSED
    assert window.tray.recording_action.text() == "기록 재개"
    ctx.stop_recording()

    again = AppContext(demo=False)
    try:
        again.start_recording()
        assert again.recording_state is RecorderState.PAUSED
        again.recorder.tick()
        assert again.recorder._probe.calls == 0  # a restored pause never reads the OS
    finally:
        again.stop_recording()
        again.service.shutdown()


def test_camera_can_be_stopped_immediately_from_the_session(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    ctx = AppContext(demo=True)
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    try:
        win.start_session(
            SessionConfig("카메라 끄기", SessionMode.CODING, 0, ("code.exe",), True)
        )
        qtbot.waitUntil(lambda: ctx.service.snapshot().active_s >= 1, timeout=6000)
        win.poll()
        assert win.session.camera_stop.isVisibleTo(win.session)
        face = ctx.service.face_source
        win.session.camera_stop.click()
        assert face.stop_count == 1 and ctx.service.face_source is None
        snap = ctx.service.snapshot()
        assert snap.camera_status is CameraStatus.OFF and snap.lifecycle is Lifecycle.RUNNING
        assert not snap.config.camera_enabled
        win.poll()
        assert not win.session.camera_stop.isVisibleTo(win.session)
    finally:
        win.close_down()


@windows_only
def test_autostart_entry_roundtrip_in_a_private_key():
    key = r"Software\FocusLab-tests\Run"
    try:
        command = autostart.enable(key)
        assert "--background" in command and "focuslab" in command.lower()
        assert autostart.is_enabled(key) and autostart.current_command(key) == command
        autostart.disable(key)
        assert not autostart.is_enabled(key)
        autostart.disable(key)  # disabling twice is fine
    finally:
        import winreg

        for sub in (key, r"Software\FocusLab-tests"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def test_launch_command_uses_windowless_python_and_data_dir(isolated_data_dir):
    command = autostart.launch_command()
    assert "--background" in command and str(isolated_data_dir) in command
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        assert "pythonw.exe" in command.lower()

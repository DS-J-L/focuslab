"""Real Win32 calls (skipped elsewhere). They read only this process and the foreground window."""

import os
import subprocess
import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


def test_process_identity_uses_executable_name_and_version_info():
    from focuslab.activity.windows_tracker import process_identity

    me = process_identity(os.getpid())
    assert me.exe_name == os.path.basename(sys.executable).lower()
    assert me.display_name  # python.exe ships a FileDescription
    assert process_identity(2**31 - 1) is None  # no such process


def test_exited_and_protected_processes_do_not_raise():
    from focuslab.activity.windows_tracker import process_identity

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert process_identity(child.pid) is None
    system = process_identity(4)  # the System process refuses its path
    assert system is not None and system.exe_name == "system"


def test_focuslab_itself_is_reported_as_self():
    from focuslab.activity.windows_tracker import foreground_app
    from focuslab.config import SELF_NAME

    assert foreground_app(0, os.getpid()).exe_name == SELF_NAME


def test_probe_sample_has_no_titles_or_paths():
    from focuslab.activity.probe import WindowsProbe

    sample = WindowsProbe().sample()
    assert sample.idle_s is not None and sample.idle_s >= 0
    if sample.app and sample.app.exe_name:
        name = sample.app.exe_name
        assert "\\" not in name and name == name.lower()


def test_event_thread_hooks_and_unhooks():
    from focuslab.activity.win_events import WindowsEventThread

    events = WindowsEventThread(lambda name: None)
    assert events.start() is True
    events.stop()
    assert not events.running
    assert not [t for t in threading.enumerate() if t.name == "focuslab-winevents"]

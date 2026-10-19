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


def test_hidden_window_translates_session_power_and_shutdown_messages():
    import ctypes

    from focuslab.activity import win_events as we

    received = []
    events = we.WindowsEventThread(received.append)
    events.start()
    try:
        assert events.session_events and events.hwnd
        send = ctypes.windll.user32.SendMessageW
        send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        send(events.hwnd, we.WM_WTSSESSION_CHANGE, 0x7, 0)  # lock
        send(events.hwnd, we.WM_WTSSESSION_CHANGE, 0x8, 0)  # unlock
        send(events.hwnd, we.WM_POWERBROADCAST, we.PBT_APMSUSPEND, 0)
        send(events.hwnd, we.WM_POWERBROADCAST, we.PBT_APMRESUMEAUTOMATIC, 0)
        send(events.hwnd, we.WM_POWERBROADCAST, we.PBT_APMRESUMESUSPEND, 0)  # same wake
        setting = we.POWERBROADCAST_SETTING(we.GUID_CONSOLE_DISPLAY_STATE, 4, 0)
        send(events.hwnd, we.WM_POWERBROADCAST, we.PBT_POWERSETTINGCHANGE,
             ctypes.addressof(setting))
        assert send(events.hwnd, we.WM_QUERYENDSESSION, 0, 0) == 1  # never blocks shutdown
        send(events.hwnd, we.WM_ENDSESSION, 1, 0)
    finally:
        events.stop()
    named = [e for e in received if e != "foreground"]
    assert named == ["lock", "unlock", "suspend", "wake", "display_off", "session_end"]

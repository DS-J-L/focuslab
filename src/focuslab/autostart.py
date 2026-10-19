"""Start FocusLab at Windows sign-in through the per-user ``Run`` registry key (no admin rights).

Only ``HKEY_CURRENT_USER`` is touched; disabling removes the value again.
"""

import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FocusLab"


def launch_command() -> str:
    """Command that starts FocusLab hidden in the tray, without a console window."""
    if getattr(sys, "frozen", False):  # packaged executable
        args = [sys.executable, "--background"]
    else:
        exe = Path(sys.executable)
        windowless = exe.with_name("pythonw.exe")
        args = [str(windowless if windowless.exists() else exe), "-m", "focuslab", "--background"]
    data_dir = os.environ.get("FOCUSLAB_DATA_DIR")
    if data_dir:
        args += ["--data-dir", data_dir]
    return subprocess.list2cmdline(args)


def current_command(key: str = RUN_KEY) -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, VALUE_NAME)
            return value
    except OSError:
        return None


def is_enabled(key: str = RUN_KEY) -> bool:
    return current_command(key) is not None


def enable(key: str = RUN_KEY, command: str | None = None) -> str:
    import winreg

    command = command or launch_command()
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        winreg.SetValueEx(handle, VALUE_NAME, 0, winreg.REG_SZ, command)
    return command


def disable(key: str = RUN_KEY) -> None:
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, VALUE_NAME)
    except FileNotFoundError:
        pass

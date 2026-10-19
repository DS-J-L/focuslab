"""Windows OS idle time via GetLastInputInfo. Only the time of the last input is read, never
which key or where the mouse was."""

import ctypes
import sys


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input in this Windows session."""
    if sys.platform != "win32":
        raise OSError("idle time is only available on Windows")
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError()
    get_tick_count = ctypes.windll.kernel32.GetTickCount
    get_tick_count.restype = ctypes.c_uint32
    # Both values are 32-bit tick counts that wrap every ~49.7 days.
    return ((get_tick_count() - info.dwTime) & 0xFFFFFFFF) / 1000

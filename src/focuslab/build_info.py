"""Which code is running: the commit and its date, and when this PC first ran it.

FocusLab.exe reads ``_build.json``, written by ``scripts/build_exe.py``. A source checkout asks
git. The version number alone cannot tell builds apart, since unreleased changes on main keep
the last release's number.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from focuslab import __version__
from focuslab.config import FROZEN

BUILD_FILE = "_build.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class BuildInfo:
    commit: str  # short SHA
    committed: datetime  # the commit's own time, local timezone
    packaged: bool  # FocusLab.exe rather than a source checkout

    @property
    def key(self) -> str:
        return f"{__version__}+{self.commit}"


def _from_file() -> BuildInfo | None:
    try:
        data = json.loads(files("focuslab").joinpath(BUILD_FILE).read_text("utf-8"))
        committed = datetime.fromisoformat(data["committed"]).astimezone()
        return BuildInfo(str(data["commit"]), committed, True)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _from_git() -> BuildInfo | None:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%h %cI"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
        )
        commit, committed = out.stdout.split()
        return BuildInfo(commit, datetime.fromisoformat(committed).astimezone(), False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def current() -> BuildInfo | None:
    "None when neither is known, e.g. an installed wheel."
    return _from_file() if FROZEN else _from_git() or _from_file()


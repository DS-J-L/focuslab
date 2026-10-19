"""Application paths, rule thresholds and per-mode defaults.

Thresholds are untuned hypotheses from DEVELOPMENT_PLAN.md section 5, not medical criteria.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from focuslab.domain.models import SessionMode

APP_NAME = "FocusLab"
RULE_VERSION = "rules-0.1"
FACE_MODEL_FILENAME = "face_landmarker.task"
REPO_MODEL_DIR = Path(__file__).resolve().parents[2] / "assets" / "models"
# Unpacked Chrome/Edge extension (loaded by the user in developer mode).
EXTENSION_DIR = Path(__file__).resolve().parents[2] / "browser_extension"
# Foreground process label reported while FocusLab itself has focus.
SELF_NAME = "focuslab"


def data_dir() -> Path:
    """Local (non-roaming) app data folder; override with FOCUSLAB_DATA_DIR."""
    override = os.environ.get("FOCUSLAB_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def db_path(base: Path | None = None) -> Path:
    return (base or data_dir()) / "focuslab.db"


def face_model_path() -> Path | None:
    """First existing face model: FOCUSLAB_MODEL_DIR, repo assets, then the data folder."""
    dirs = [Path(d) for d in [os.environ.get("FOCUSLAB_MODEL_DIR")] if d]
    dirs += [REPO_MODEL_DIR, data_dir() / "models"]
    for d in dirs:
        candidate = d / FACE_MODEL_FILENAME
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class RuleConfig:
    face_ttl_ms: int = 2_000
    activity_ttl_ms: int = 3_000
    min_face_quality: float = 0.35
    unrelated_app_s: float = 15
    head_away_idle_s: float = 10
    away_idle_s: float = 20
    active_idle_s: float = 30
    pc_only_idle_s: float = 120
    enter_dwell_s: float = 3
    max_gap_fill_s: int = 600


@dataclass(frozen=True)
class ModeProfile:
    head_down_is_work: bool
    idle_is_normal: bool
    away_face_absent_s: float
    head_away_s: float


MODE_PROFILES = {
    SessionMode.CODING: ModeProfile(False, False, 20, 15),
    SessionMode.LECTURE: ModeProfile(False, True, 20, 15),
    SessionMode.READING_WRITING: ModeProfile(True, True, 60, 30),
    SessionMode.CUSTOM: ModeProfile(False, False, 20, 15),
}

MODE_LABELS = {
    SessionMode.CODING: "코딩",
    SessionMode.LECTURE: "강의",
    SessionMode.READING_WRITING: "독서·필기",
    SessionMode.CUSTOM: "사용자 지정",
}

BROWSERS = (
    "chrome.exe", "msedge.exe", "firefox.exe", "whale.exe", "brave.exe", "opera.exe",
)

# Apps that are neither evidence of work nor of deviation (desktop shell, this app).
NEUTRAL_APPS = (
    "explorer.exe", "searchhost.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "applicationframehost.exe", SELF_NAME,
)

LOCK_APPS = ("lockapp.exe", "logonui.exe")

DEFAULT_ALLOWED_APPS = {
    SessionMode.CODING: (
        "code.exe", "cursor.exe", "pycharm64.exe", "idea64.exe", "devenv.exe",
        "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "notepad++.exe",
        "claude.exe", *BROWSERS,
    ),
    SessionMode.LECTURE: (
        *BROWSERS, "vlc.exe", "potplayermini64.exe", "zoom.exe", "ms-teams.exe",
        "acrobat.exe", "sumatrapdf.exe",
    ),
    SessionMode.READING_WRITING: (
        "acrobat.exe", "acrord32.exe", "sumatrapdf.exe", "winword.exe", "onenote.exe",
        "notion.exe", "obsidian.exe", "hwp.exe", "notepad.exe", *BROWSERS,
    ),
    SessionMode.CUSTOM: (),
}

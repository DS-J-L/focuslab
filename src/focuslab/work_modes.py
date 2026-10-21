"""Work modes offered for a new session: the built-in ones, presets and the user's own.

A preset or a user's mode has its own name and allowed apps and is estimated like one built-in
mode (its base), so the rule engine only ever sees a SessionMode. Sessions keep the name as it
was.
"""

import json
import uuid
from dataclasses import dataclass

from focuslab.config import (
    BROWSERS,
    DEFAULT_ALLOWED_APPS,
    ESTIMATION_HINTS,
    MODE_HINTS,
    MODE_LABELS,
)
from focuslab.domain.models import SessionMode
from focuslab.i18n import tr

CUSTOM_PREFIX = "custom:"
PRESET_PREFIX = "preset:"
# CUSTOM estimates exactly like CODING, so it is not offered as a base.
BASES = (SessionMode.CODING, SessionMode.LECTURE, SessionMode.READING_WRITING)
MAX_NAME = 40


@dataclass(frozen=True)
class WorkMode:
    key: str  # the SessionMode value for built-ins, ``preset:<id>``, ``custom:<id>``
    base: SessionMode
    name: str | None = None  # None for built-ins; a preset's is translated when shown
    apps: tuple[str, ...] | None = None  # a preset's own defaults
    about: str | None = None  # a preset's hint, translated when shown

    @property
    def preset(self) -> bool:
        return self.key.startswith(PRESET_PREFIX)

    @property
    def label(self) -> str:
        if self.preset:
            return tr(self.name)
        return self.name or MODE_LABELS[self.base]

    @property
    def session_name(self) -> str | None:
        "The name a session keeps; None for built-ins."
        return self.label if self.name is not None else None

    @property
    def hint(self) -> str:
        if self.name is None:
            return MODE_HINTS[self.base]
        if self.preset:
            return tr(self.about) + " " + tr("Estimated like {p0}.", p0=MODE_LABELS[self.base])
        return tr(
            "Estimated like {p0}. {p1}",
            p0=MODE_LABELS[self.base],
            p1=ESTIMATION_HINTS[self.base],
        )

    @property
    def default_apps(self) -> tuple[str, ...]:
        return self.apps if self.apps is not None else DEFAULT_ALLOWED_APPS[self.base]


BUILT_IN = tuple(WorkMode(mode.value, mode) for mode in SessionMode)

MEETING = "Meeting / video call"
DESIGN = "Design"
OFFICE = "Office documents"
EXAM = "Exam prep / problem solving"
DATA = "Data analysis"
VIDEO = "Video editing"
LANGUAGE = "Language study"
MUSIC = "Music production"


def _preset(key: str, base: SessionMode, name: str, about: str, *apps: str) -> WorkMode:
    return WorkMode(PRESET_PREFIX + key, base, name, apps, about)


# Common jobs that the three built-in estimations already fit, with their usual apps.
PRESETS = (
    _preset(
        "meeting", SessionMode.LECTURE, MEETING, "Zoom, Teams, Webex and calls in the browser.",
        "zoom.exe", "ms-teams.exe", "teams.exe", "webex.exe", "ciscocollabhost.exe",
        "slack.exe", *BROWSERS,
    ),
    _preset(
        "design", SessionMode.CODING, DESIGN, "Figma, Adobe apps, Blender and references.",
        "figma.exe", "photoshop.exe", "illustrator.exe", "indesign.exe", "afterfx.exe",
        "xd.exe", "blender.exe", "clipstudiopaint.exe", "krita.exe", *BROWSERS,
    ),
    _preset(
        "office", SessionMode.CODING, OFFICE, "Word, Excel, PowerPoint, Hangul and mail.",
        "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "onenote.exe", "hwp.exe",
        "hcell.exe", "hshow.exe", "notion.exe", "acrobat.exe", *BROWSERS,
    ),
    _preset(
        "exam", SessionMode.READING_WRITING, EXAM,
        "Workbooks and paper with PDFs, flashcards and lecture notes.",
        "acrobat.exe", "acrord32.exe", "sumatrapdf.exe", "anki.exe", "onenote.exe",
        "notion.exe", "obsidian.exe", *BROWSERS,
    ),
    _preset(
        "data", SessionMode.CODING, DATA, "Excel, Jupyter, RStudio, BI tools and SQL clients.",
        "excel.exe", "code.exe", "pycharm64.exe", "rstudio.exe", "pbidesktop.exe",
        "tableau.exe", "dbeaver.exe", "ssms.exe", *BROWSERS,
    ),
    _preset(
        "video", SessionMode.CODING, VIDEO, "Premiere Pro, DaVinci Resolve, CapCut and Vegas.",
        "adobe premiere pro.exe", "afterfx.exe", "resolve.exe", "capcut.exe", "vegas.exe",
        "audition.exe", "obs64.exe", *BROWSERS,
    ),
    _preset(
        "language", SessionMode.LECTURE, LANGUAGE,
        "Lessons, dictionaries and listening; no typing is expected.",
        "anki.exe", "vlc.exe", "potplayermini64.exe", "zoom.exe", "acrobat.exe",
        "sumatrapdf.exe", *BROWSERS,
    ),
    _preset(
        "music", SessionMode.CODING, MUSIC, "FL Studio, Ableton Live, REAPER and other DAWs.",
        "fl64.exe", "ableton live 12 suite.exe", "ableton live 11 suite.exe", "studio one.exe",
        "reaper.exe", "musescore4.exe", *BROWSERS,
    ),
)


def clean_name(name: str) -> str:
    return " ".join(name.split())[:MAX_NAME]


def new_mode(name: str, base: SessionMode) -> WorkMode:
    return WorkMode(CUSTOM_PREFIX + uuid.uuid4().hex[:8], base, clean_name(name))


def load_custom(raw: str | None) -> list[WorkMode]:
    "Saved modes; malformed entries and unknown bases are skipped, never fatal."
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    modes = []
    for item in items if isinstance(items, list) else []:
        try:
            mode = WorkMode(str(item["key"]), SessionMode(item["base"]), clean_name(item["name"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if mode.key.startswith(CUSTOM_PREFIX) and mode.name:
            modes.append(mode)
    return modes


def dump_custom(modes: list[WorkMode]) -> str:
    return json.dumps(
        [{"key": m.key, "base": m.base.value, "name": m.name} for m in modes], ensure_ascii=False
    )

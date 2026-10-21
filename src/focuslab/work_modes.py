"""Work modes offered for a new session: the built-in ones and the user's own.

A user's mode has its own name and allowed apps and is estimated like one built-in mode (its
base), so the rule engine only ever sees a SessionMode. Sessions keep the name as it was.
"""

import json
import uuid
from dataclasses import dataclass

from focuslab.config import DEFAULT_ALLOWED_APPS, ESTIMATION_HINTS, MODE_HINTS, MODE_LABELS
from focuslab.domain.models import SessionMode
from focuslab.i18n import tr

CUSTOM_PREFIX = "custom:"
# CUSTOM estimates exactly like CODING, so it is not offered as a base.
BASES = (SessionMode.CODING, SessionMode.LECTURE, SessionMode.READING_WRITING)
MAX_NAME = 40


@dataclass(frozen=True)
class WorkMode:
    key: str  # the SessionMode value for built-ins, ``custom:<id>`` for the user's own
    base: SessionMode
    name: str | None = None  # None for built-ins

    @property
    def label(self) -> str:
        return self.name or MODE_LABELS[self.base]

    @property
    def hint(self) -> str:
        if self.name is None:
            return MODE_HINTS[self.base]
        return tr(
            "Estimated like {p0}. {p1}",
            p0=MODE_LABELS[self.base],
            p1=ESTIMATION_HINTS[self.base],
        )

    @property
    def default_apps(self) -> tuple[str, ...]:
        return DEFAULT_ALLOWED_APPS[self.base]


BUILT_IN = tuple(WorkMode(mode.value, mode) for mode in SessionMode)


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

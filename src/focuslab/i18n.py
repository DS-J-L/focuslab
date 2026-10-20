"""English message IDs with a Korean catalog; no translated text is used as a data key.

Language is selected once at startup. Settings persist the next launch's choice so that
changing the interface never rebuilds a running session or discards an unsaved form.
"""

import json
import locale
import os
from collections.abc import Iterator, Mapping
from functools import lru_cache
from importlib.resources import files
from typing import TypeVar

SUPPORTED_LANGUAGES = {"en": "English", "ko": "한국어"}
_language: str | None = None
K = TypeVar("K")


def system_language() -> str:
    """Use the OS display language, with English as the unsupported-locale fallback."""
    from PySide6.QtCore import QLocale

    name = QLocale.system().name() or locale.getlocale()[0] or "en"
    return "ko" if name.lower().startswith("ko") else "en"


def set_language(language: str) -> None:
    global _language
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    _language = language


def initialize_language(saved: str | None = None) -> str:
    """A CLI/environment override wins over the saved preference and OS language."""
    selected = os.environ.get("FOCUSLAB_LANGUAGE") or saved
    set_language(selected if selected in SUPPORTED_LANGUAGES else system_language())
    return get_language()


def get_language() -> str:
    if _language is None:
        return initialize_language()
    return _language


@lru_cache(maxsize=1)
def korean_catalog() -> dict[str, str]:
    return json.loads(files("focuslab").joinpath("locales", "ko.json").read_text("utf-8"))


def tr(message: str, **values: object) -> str:
    """Translate a complete message, then format named placeholders.

    Values (goals, app names, paths, and observations) are never translated. Unknown
    message IDs fall back to their English source so optional extensions remain usable.
    """
    template = korean_catalog().get(message, message) if get_language() == "ko" else message
    return template.format(**values) if values else template


class LocalizedMapping(Mapping[K, str]):
    """Labels resolve at access time, including dictionaries imported before startup."""

    def __init__(self, messages: Mapping[K, str]) -> None:
        self._messages = dict(messages)

    def __getitem__(self, key: K) -> str:
        return tr(self._messages[key])

    def __iter__(self) -> Iterator[K]:
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)


def weekday_name(index: int) -> str:
    if get_language() == "ko":
        return ("월", "화", "수", "목", "금", "토", "일")[index]
    return ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[index]


def install_qt_translator(app) -> None:
    """Translate standard Qt buttons too. Keep the translator alive on the app."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    previous = getattr(app, "_focuslab_translator", None)
    if previous is not None:
        app.removeTranslator(previous)
    translator = QTranslator(app)
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(get_language()), "qtbase", "_", directory):
        app.installTranslator(translator)
    app._focuslab_translator = translator

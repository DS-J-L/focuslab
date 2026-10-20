"""One-click extension setup from Settings.

With a published store listing the browser opens its store page ("Add to Chrome"). Until then
Windows Chrome/Edge only accept an unpacked extension that the user loads in Developer mode, so
the app copies it into the data folder (rebuilding or moving the app cannot remove what the
browser loaded) and shows it in Explorer next to the browser. Browsers refuse chrome:// and
edge:// URLs from the command line, so the extensions page address goes to the clipboard.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from focuslab.browser import STORE_IDS, STORE_URLS
from focuslab.config import EXTENSION_DIR, data_dir

STAGED_FOLDER = "browser-extension"
SKIP = shutil.ignore_patterns("test", "package.json", "node_modules")
BROWSER_APPS = {"chrome": "chrome.exe", "edge": "msedge.exe"}
EXTENSIONS_PAGES = {"chrome": "chrome://extensions/", "edge": "edge://extensions/"}


def browser_executable(browser: str) -> Path | None:
    """Installed browser from the per-user or machine App Paths entry (read-only)."""
    if sys.platform != "win32":
        return None
    import winreg

    key = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{BROWSER_APPS[browser]}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        path = Path(value.strip('"'))
        if path.is_file():
            return path
    return None


def store_url(browser: str) -> str | None:
    item = STORE_IDS.get(browser)
    return STORE_URLS[browser].format(id=item) if item else None


def stage_extension(folder: Path | None = None) -> Path:
    dest = (folder or data_dir()) / STAGED_FOLDER
    shutil.rmtree(dest, ignore_errors=True)  # drop files an older version no longer ships
    shutil.copytree(EXTENSION_DIR, dest, ignore=SKIP)
    return dest


def open_in_browser(browser: str, url: str | None = None) -> None:
    """Open ``url`` (an ordinary web address), or just bring up a new browser window."""
    executable = browser_executable(browser)
    if executable is None:
        raise FileNotFoundError(f"{BROWSER_APPS[browser]} is not installed")
    subprocess.Popen([str(executable), url or "--new-window"])


def reveal(path: Path) -> None:
    """Open Explorer with ``path`` selected, ready to drag onto the extensions page."""
    subprocess.Popen(f'explorer /select,"{path}"')

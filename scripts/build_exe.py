"""Build the Windows desktop app as ``dist/FocusLab/FocusLab.exe`` with PyInstaller.

    uv run --group build python scripts/build_exe.py

The result is a folder build (FocusLab.exe next to ``_internal/``): it starts quickly and the
sign-in autostart entry and browser native host can point at the exe directly. Copy or zip the
whole ``dist/FocusLab`` folder; the exe does not run on its own.

Bundled data: the Korean catalog (``focuslab/locales``), the face model when
``assets/models/face_landmarker.task`` exists (otherwise the app downloads it into the user's
data folder), the unpacked browser extension, and Qt's own translations (PySide6 hook).
MediaPipe and OpenCV binaries come from the PyInstaller hooks.
"""

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "assets" / "models" / "face_landmarker.task"
EXTENSION = ROOT / "browser_extension"
EXTENSION_FILES = ("manifest.json", "background.js", "logic.js")


def data(source: Path, dest: str) -> str:
    return f"--add-data={source}{os.pathsep}{dest}"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("FocusLab.exe is built on Windows only")
    args = [
        str(ROOT / "src" / "focuslab" / "__main__.py"),
        "--name=FocusLab",
        "--windowed",
        f"--icon={ROOT / 'src' / 'focuslab' / 'ui' / 'icons' / 'parrot-telescope.ico'}",
        "--noconfirm",
        "--clean",
        f"--paths={ROOT / 'src'}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT / 'build'}",
        "--collect-data=focuslab",  # locales/ko.json, read through importlib.resources
        *(data(EXTENSION / name, "browser_extension") for name in EXTENSION_FILES),
    ]
    if MODEL.is_file():
        args.append(data(MODEL, "assets/models"))
    else:
        print("note: no face model in assets/models; FocusLab.exe will download it on first use")
    PyInstaller.__main__.run(args)
    print(f"\nBuilt {ROOT / 'dist' / 'FocusLab' / 'FocusLab.exe'}")


if __name__ == "__main__":
    main()

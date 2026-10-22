"""Build the Windows desktop app as ``dist/FocusLab/FocusLab.exe`` with PyInstaller.

    uv run --group build python scripts/build_exe.py

The result is a folder build (FocusLab.exe next to ``_internal/``): it starts quickly and the
sign-in autostart entry and browser native host can point at the exe directly. Copy or zip the
whole ``dist/FocusLab`` folder; the exe does not run on its own.

Bundled data: ``focuslab/_build.json`` (the commit Settings > Updates shows), the Korean
catalog (``focuslab/locales``), the face model when
``assets/models/face_landmarker.task`` exists (otherwise the app downloads it into the user's
data folder), the unpacked browser extension, and Qt's own translations (PySide6 hook).
MediaPipe and OpenCV binaries come from the PyInstaller hooks.
"""

import filecmp
import json
import os
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "assets" / "models" / "face_landmarker.task"
EXTENSION = ROOT / "browser_extension"
EXTENSION_FILES = ("manifest.json", "background.js", "logic.js")
PYTHON_DLLS = Path(sys.base_prefix) / "DLLs"
# Python's own OpenSSL; builds name it differently (libssl-3.dll, libssl-3-x64.dll).
OPENSSL_PATTERNS = ("libssl-3*.dll", "libcrypto-3*.dll")


def data(source: Path, dest: str) -> str:
    return f"--add-data={source}{os.pathsep}{dest}"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def build_record() -> Path:
    "The commit this build comes from; '-modified' marks uncommitted changes in the tree."
    commit, committed = git("log", "-1", "--format=%h %cI").split()
    if git("status", "--porcelain", "--untracked-files=no"):
        commit += "-modified"
    path = ROOT / "build" / "_build.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"commit": commit, "committed": committed}), "utf-8")
    return path


def python_openssl() -> list[Path]:
    found = [dll for pattern in OPENSSL_PATTERNS for dll in sorted(PYTHON_DLLS.glob(pattern))]
    if len(found) != len(OPENSSL_PATTERNS):
        raise SystemExit(f"expected one libssl and one libcrypto in {PYTHON_DLLS}, found {found}")
    return found


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
        # mediapipe loads tasks/c/libmediapipe.dll through ctypes, which no hook detects.
        "--collect-binaries=mediapipe",
        *(data(EXTENSION / name, "browser_extension") for name in EXTENSION_FILES),
        data(build_record(), "focuslab"),
    ]
    if (EXTENSION / "icons").is_dir():  # manifest icons, once the extension ships them
        args.append(data(EXTENSION / "icons", "browser_extension/icons"))
    if MODEL.is_file():
        args.append(data(MODEL, "assets/models"))
    else:
        print("note: no face model in assets/models; FocusLab.exe will download it on first use")
    # Qt's TLS plugin pulls in libssl/libcrypto by name and PyInstaller resolves those through
    # PATH, where another OpenSSL (e.g. Git's mingw64\bin) can win. _ssl.pyd then fails to load
    # and urllib loses https ("unknown url type: https"), so Python's own copies go first.
    os.environ["PATH"] = os.pathsep.join([str(PYTHON_DLLS), os.environ.get("PATH", "")])
    PyInstaller.__main__.run(args)
    internal = ROOT / "dist" / "FocusLab" / "_internal"
    dll = internal / "mediapipe" / "tasks" / "c" / "libmediapipe.dll"
    if not dll.is_file():
        raise SystemExit(f"build is missing {dll}; the face model would fail to load")
    for dll in python_openssl():
        bundled = internal / dll.name
        if not bundled.is_file() or not filecmp.cmp(bundled, dll, shallow=False):
            raise SystemExit(f"build bundled a foreign {dll.name}; downloads over https would fail")
    print(f"\nBuilt {ROOT / 'dist' / 'FocusLab' / 'FocusLab.exe'}")


if __name__ == "__main__":
    main()

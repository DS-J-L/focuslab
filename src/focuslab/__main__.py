"""Command line entry point: ``focuslab`` opens the desktop app."""

import argparse
import logging
import os
import platform
import sys
from pathlib import Path

from focuslab import __version__


def _check() -> int:
    """Print environment status without opening sensors or writing user data."""
    from focuslab.config import data_dir, db_path, face_model_path
    from focuslab.model_fetch import FACE_MODEL_SHA256, sha256

    model = face_model_path()
    if model is None:
        model_text = "missing (run: focuslab --fetch-models)"
    else:
        ok = sha256(model) == FACE_MODEL_SHA256
        model_text = f"{model} ({'sha256 ok' if ok else 'SHA256 MISMATCH'})"
    lines = [
        f"FocusLab {__version__}",
        f"Python {platform.python_version()} on {platform.platform()}",
        f"Data folder: {data_dir()}",
        f"Database: {db_path()} ({'exists' if db_path().exists() else 'not created yet'})",
        f"Face model: {model_text}",
    ]
    for module in ("PySide6", "cv2", "mediapipe", "psutil"):
        try:
            mod = __import__(module)
            lines.append(f"{module}: {getattr(mod, '__version__', 'ok')}")
        except Exception as exc:  # report, do not crash
            lines.append(f"{module}: unavailable ({exc})")
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="focuslab",
        description="Local-first Windows work-pattern observation (not a diagnostic tool).",
    )
    parser.add_argument("--version", action="version", version=f"FocusLab {__version__}")
    parser.add_argument("--demo", action="store_true",
                        help="use scripted sensors; never reads the camera or PC activity")
    parser.add_argument("--data-dir", type=Path, help="override the local data folder")
    parser.add_argument("--check", action="store_true", help="print environment status and exit")
    parser.add_argument("--fetch-models", action="store_true",
                        help="download the MediaPipe face model and verify its SHA256")
    parser.add_argument("--seed-demo", action="store_true",
                        help="add synthetic demo sessions to the local database and exit")
    parser.add_argument("--background", action="store_true",
                        help="start minimized to the tray (used by the sign-in autostart entry)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.data_dir:
        os.environ["FOCUSLAB_DATA_DIR"] = str(args.data_dir)
    if args.check:
        return _check()
    if args.fetch_models:
        from focuslab.model_fetch import fetch_face_model

        print(f"Face model ready: {fetch_face_model()}")
        return 0
    if args.seed_demo:
        from focuslab.config import db_path
        from focuslab.demo import seed_demo_sessions

        ids = seed_demo_sessions(db_path())
        print(f"Added {len(ids)} demo sessions to {db_path()}")
        return 0

    from focuslab.ui.main_window import run_app

    return run_app(demo=args.demo, background=args.background)


if __name__ == "__main__":
    sys.exit(main())

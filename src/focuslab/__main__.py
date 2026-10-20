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
    if sys.platform == "win32":  # read-only registry lookups
        from focuslab import autostart
        from focuslab.browser.install import registered

        hosts = [name for name, ok in registered().items() if ok]
        lines.append(f"Start at sign-in: {'on' if autostart.is_enabled() else 'off'}")
        lines.append(f"Browser bridge: {', '.join(hosts) if hosts else 'not installed'}")
    from focuslab.relevance import model_manager

    folder = model_manager.installed_dir()
    lines.append(
        f"Relevance model: {folder} ({model_manager.MODEL_VERSION})"
        if folder
        else "Relevance model: not installed (optional; Settings -> Task relevance AI)"
    )
    for module in ("PySide6", "cv2", "mediapipe", "psutil", "onnxruntime", "sentencepiece"):
        try:
            mod = __import__(module)
            lines.append(f"{module}: {getattr(mod, '__version__', 'ok')}")
        except Exception as exc:  # report, do not crash
            lines.append(f"{module}: unavailable ({exc})")
    print("\n".join(lines))
    return 0


def _relevance_selftest() -> int:
    """Load the installed relevance model and compare two titles with a goal.

    Exit 0 when the model is not installed (it is optional) or behaves as expected, 1 when
    the runtime is missing or the model cannot load or ranks the titles the wrong way round.
    """
    import time

    from focuslab.relevance import model_manager
    from focuslab.relevance.embedding import SemanticAnalyzer

    status = model_manager.status()
    print(f"Relevance model status: {status.value}")
    if status is model_manager.ModelStatus.NOT_INSTALLED:
        return 0
    if status is model_manager.ModelStatus.RUNTIME_MISSING:
        return 1
    folder = model_manager.installed_dir()
    started = time.perf_counter()
    try:
        embedder = model_manager.load(folder)
    except Exception as exc:  # report, do not crash
        print(f"Relevance model failed to load: {exc}")
        return 1
    print(f"Verified and loaded {folder} in {time.perf_counter() - started:.2f} s")
    analyzer = SemanticAnalyzer(lambda: embedder, model_manager.MODEL_VERSION)
    goal = "증강현실 프로그래밍 공부"
    titles = ("ARCore 평면 인식 원리", "침착맨 삼국지 정주행")
    try:
        for title in titles:
            analyzer.lookup(goal, title)
            analyzer.wait_idle(30)
        margins = [analyzer.lookup(goal, title) for title in titles]
    finally:
        analyzer.close()
    for title, margin in zip(titles, margins, strict=True):
        print(f"  {goal} | {title}: margin {margin}")
    ok = None not in margins and margins[0] > margins[1]
    print("Relevance self-test: " + ("ok" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    raw = sys.argv[1:] if argv is None else argv
    if any(a.startswith("chrome-extension://") for a in raw):
        # A packaged FocusLab.exe registered as the browser's native messaging host.
        from focuslab.browser.native_host import main as native_host

        return native_host(raw)
    parser = argparse.ArgumentParser(
        prog="focuslab",
        description="Local-first Windows work-pattern observation (not a diagnostic tool).",
    )
    parser.add_argument("--version", action="version", version=f"FocusLab {__version__}")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="use scripted sensors; never reads the camera or PC activity",
    )
    parser.add_argument("--data-dir", type=Path, help="override the local data folder")
    parser.add_argument(
        "--language", choices=("en", "ko"), help="override the interface language for this run"
    )
    parser.add_argument("--check", action="store_true", help="print environment status and exit")
    parser.add_argument(
        "--fetch-models",
        action="store_true",
        help="download the MediaPipe face model and verify its SHA256",
    )
    parser.add_argument(
        "--relevance-selftest",
        action="store_true",
        help="load the optional task-relevance model, if installed, and test it",
    )
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="add synthetic demo sessions to the local database and exit",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="start minimized to the tray (used by the sign-in autostart entry)",
    )
    args = parser.parse_args(raw)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.data_dir:
        os.environ["FOCUSLAB_DATA_DIR"] = str(args.data_dir)
    if args.language:
        os.environ["FOCUSLAB_LANGUAGE"] = args.language
    if args.check:
        return _check()
    if args.relevance_selftest:
        return _relevance_selftest()
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

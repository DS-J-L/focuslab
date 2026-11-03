"""Sensor-free preview of the actual session overlay, also available in the EXE."""

import os
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.overlay import SessionOverlay
from focuslab.ui.theme import apply_theme


def run(
    snapshot: Path | None = None, scale: float = 1,
    state: str = "focusing", behavior: str | None = None, at: float = 0,
) -> int:
    if snapshot is not None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = str(scale)
    previous_dir = os.environ.get("FOCUSLAB_DATA_DIR")
    with TemporaryDirectory(prefix="focuslab-mascot-preview-") as folder:
        os.environ["FOCUSLAB_DATA_DIR"] = folder
        app = QApplication(sys.argv[:1])
        apply_theme(app)
        ctx = AppContext(demo=True)
        overlay = SessionOverlay(ctx)
        overlay.setWindowTitle("FocusLab — Parrot preview")
        overlay.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        service = ctx.service

        def refresh() -> None:
            overlay.refresh(service.snapshot())

        def pause() -> None:
            if service.snapshot().lifecycle is Lifecycle.PAUSED:
                service.resume()
            else:
                service.pause()
            refresh()

        def take_break() -> None:
            service.set_break(not service.snapshot().on_break)
            refresh()

        overlay.pauseRequested.connect(pause)
        overlay.breakRequested.connect(take_break)
        overlay.finishRequested.connect(app.quit)
        overlay.close_button.clicked.connect(app.quit)
        service.start(SessionConfig("Parrot preview", SessionMode.CODING, 25, (), False))
        if state == "paused":
            service.pause()
        elif state == "break":
            service.set_break(True)
        overlay.start(service.snapshot())
        timer = QTimer(interval=250)
        timer.timeout.connect(refresh)
        timer.start()
        try:
            if snapshot is not None:
                director = overlay.perch.director
                director.set_motion("minimal")
                overlay.perch.clock = lambda: 100.0 + at
                if behavior is not None:
                    for actor in director.actors:
                        actor.play(director.behaviors[behavior], 100.0)
                overlay.refresh(replace(service.snapshot(), active_s=754))
                app.processEvents()
                pixmap = QPixmap(overlay.size() * scale)
                pixmap.setDevicePixelRatio(scale)
                pixmap.fill(Qt.GlobalColor.transparent)
                overlay.render(pixmap)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                if not pixmap.save(str(snapshot)):
                    raise RuntimeError(f"Cannot save preview: {snapshot}")
                print(snapshot.resolve())
                return 0
            return app.exec()
        finally:
            timer.stop()
            overlay.close()
            service.shutdown()
            if previous_dir is None:
                os.environ.pop("FOCUSLAB_DATA_DIR", None)
            else:
                os.environ["FOCUSLAB_DATA_DIR"] = previous_dir

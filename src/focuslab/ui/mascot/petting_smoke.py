"""Exercise hover petting in the frozen app using isolated, local Qt input events.

No application context, sensors, user database or global pointer input is used.
"""

import json
import os
from pathlib import Path


def run(report: Path) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from focuslab.i18n import tr
    from focuslab.ui.overlay import SEATS, PerchView
    from focuslab.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    clock = [100.0]
    view = PerchView(clock=lambda: clock[0])
    view.setObjectName("Overlay")
    view.status.setText(tr("Focusing"))
    view.time.setText("00:00")
    clicks = []
    for button, icon in zip(view.parrots, ("pause", "stop", "cup"), strict=True):
        button.emblem = button.icon_name = icon
        button.clicked.connect(lambda: clicks.append(True))
    result = {}
    try:
        view.show()
        app.processEvents()
        for i, button in enumerate(view.parrots):
            QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
            for y in (100, 120, 140, 120, 100, 120, 140):
                clock[0] += .12
                pos = QPointF(SEATS[i], y) - QPointF(button.pos())
                global_pos = QPointF(button.mapToGlobal(pos.toPoint()))
                event = QMouseEvent(QEvent.Type.MouseMove, pos, global_pos,
                                    Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                    Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(button, event)
                view.director.poses(clock[0])
            if not view.director.actors[i].content(clock[0]):
                raise RuntimeError(f"parrot {i} did not recognize hover strokes")
            QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        for _ in range(30):
            clock[0] += 1 / 60
            poses = view.director.poses(clock[0])
        if clicks or poses[-1].eye_open >= .75 or not all(abs(p.head_tilt) > 3 for p in poses):
            raise RuntimeError("petting activated a control or did not soften the eyes")
        report.parent.mkdir(parents=True, exist_ok=True)
        if not view.grab().save(str(report.with_suffix(".png"))):
            raise RuntimeError("could not render petting preview")
        clock[0] += 5
        view.director.poses(clock[0])
        if not all(a.content(clock[0]) for a in view.director.actors):
            raise RuntimeError("contentment did not remain after the pointer left")
        clock[0] += 25
        view.director.poses(clock[0])
        if any(a.content(clock[0]) for a in view.director.actors):
            raise RuntimeError("contentment did not expire")
        result = {"ok": True, "petted_birds": 3, "control_clicks": 0,
                  "contentment_lingers_and_expires": True,
                  "input": "local Qt hover events; no global mouse or user data"}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        view.close()
        app.processEvents()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("ok") else 1

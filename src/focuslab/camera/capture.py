"""Webcam capture worker. Holds only the newest frame in memory; nothing is recorded or saved.

The device is opened on the worker thread (opening can take seconds on Windows)
and released as soon as ``stop`` is called. Read failures mark the camera
DISCONNECTED and the worker retries periodically.
"""

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from focuslab.domain.models import CameraStatus

log = logging.getLogger(__name__)

_FAILURES_BEFORE_DISCONNECT = 15
_REOPEN_DELAY_S = 2.0


@dataclass(frozen=True)
class Frame:
    id: int
    image: np.ndarray  # BGR


def _open(index: int, width: int, height: int):
    import cv2

    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, _ = cap.read()
            if ok:
                return cap
        cap.release()
    return None


class CameraCapture:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480) -> None:
        self.index = index
        self._size = (width, height)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame: Frame | None = None
        self._status = CameraStatus.OFF

    @property
    def status(self) -> CameraStatus:
        return self._status

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._status = CameraStatus.STARTING
        self._thread = threading.Thread(target=self._run, name="focuslab-camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        with self._lock:
            self._frame = None
        self._status = CameraStatus.OFF

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frame

    def _run(self) -> None:
        cap = None
        frame_id = 0
        failures = 0
        try:
            while not self._stop.is_set():
                if cap is None:
                    cap = _open(self.index, *self._size)
                    if cap is None:
                        # First attempt failing usually means no device or privacy block.
                        self._status = (
                            CameraStatus.NO_DEVICE if frame_id == 0 else CameraStatus.DISCONNECTED
                        )
                        self._stop.wait(_REOPEN_DELAY_S)
                        continue
                    failures = 0
                    self._status = CameraStatus.RUNNING
                ok, image = cap.read()
                if not ok or image is None:
                    failures += 1
                    if failures >= _FAILURES_BEFORE_DISCONNECT:
                        log.warning("camera %s stopped delivering frames", self.index)
                        cap.release()
                        cap = None
                        with self._lock:
                            self._frame = None
                        self._status = CameraStatus.DISCONNECTED
                    time.sleep(0.05)
                    continue
                failures = 0
                frame_id += 1
                with self._lock:
                    self._frame = Frame(frame_id, image)
        except Exception:
            log.exception("camera worker failed")
            self._status = CameraStatus.DISCONNECTED
        finally:
            if cap is not None:
                cap.release()

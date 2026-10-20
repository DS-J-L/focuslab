"""One-click update: download, SHA256 check and unpack on a worker thread with one progress
bar, then hand the unpacked folder over for the restart. Cancel stops at the next chunk or
file and keeps nothing."""

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focuslab import __version__, updater
from focuslab.config import data_dir
from focuslab.i18n import tr

DOWNLOAD, UNPACK = "download", "unpack"
# Share of the bar per step: the download dominates; unpacking is local and quicker.
WEIGHT = {DOWNLOAD: 0.8, UNPACK: 0.2}
READY_PAUSE_MS = 1200  # let "100%" be seen before FocusLab quits for the swap
MB = 1024 * 1024


class _Signals(QObject):
    progress = Signal(str, int, int)  # step, done bytes, total bytes (0 when unknown)
    finished = Signal(object)  # unpacked folder, UpdateCancelled or another exception


def _mb(n: int) -> str:
    return f"{n / MB:.1f}"


class UpdateDialog(QDialog):
    ready = Signal(object)  # unpacked folder to swap in after quitting
    failed = Signal(object)  # the exception shown in the dialog
    cancelled = Signal()

    def __init__(self, release: updater.Release, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self.setWindowTitle(tr("Update FocusLab"))
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(10)
        title = QLabel(
            tr("FocusLab {p0} → {p1}", p0=__version__, p1=release.version),
            objectName="PageTitle",
        )
        root.addWidget(title)
        self.step = QLabel(tr("Downloading…"))
        root.addWidget(self.step)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        root.addWidget(self.bar)
        detail_row = QHBoxLayout()
        self.detail = QLabel("", objectName="Muted")
        self.percent = QLabel("0%", objectName="Muted")
        detail_row.addWidget(self.detail, 1)
        detail_row.addWidget(self.percent, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(detail_row)
        self.note = QLabel(
            tr("FocusLab restarts to finish the update; your records and settings are kept."),
            objectName="Muted",
            wordWrap=True,
        )
        root.addWidget(self.note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self._stop = threading.Event()
        self._running = False
        self._started = 0.0
        self._signals = _Signals()
        self._signals.progress.connect(self._progress)
        self._signals.finished.connect(self._finished)

    # worker -----------------------------------------------------------------------------
    def start(self) -> None:
        "Show the dialog and begin at once: pressing Update was the decision."
        self._running = True
        self._started = time.monotonic()
        self.show()
        threading.Thread(target=self._work, name="focuslab-update", daemon=True).start()

    def _work(self) -> None:
        emit = self._signals.progress.emit
        try:
            package = updater.download(
                self.release,
                data_dir() / "updates",
                lambda done, total: emit(DOWNLOAD, done, total),
                self._stop.is_set,
            )
            try:
                staged = updater.stage(
                    package,
                    updater.install_dir(),
                    lambda done, total: emit(UNPACK, done, total),
                    self._stop.is_set,
                )
            finally:
                package.unlink(missing_ok=True)
            self._signals.finished.emit(staged)
        except Exception as exc:  # cancel, network, checksum and disk errors
            self._signals.finished.emit(exc)

    # progress ---------------------------------------------------------------------------
    def _progress(self, step: str, done: int, total: int) -> None:
        if self._stop.is_set():
            return
        base = 0.0 if step == DOWNLOAD else WEIGHT[DOWNLOAD]
        if step == DOWNLOAD:
            self.step.setText(tr("Downloading…"))
            elapsed = max(time.monotonic() - self._started, 1e-3)
            speed = tr("{p0} MB/s", p0=_mb(int(done / elapsed)))
            if total:
                self.detail.setText(
                    tr("{p0} / {p1} MB · {p2}", p0=_mb(done), p1=_mb(total), p2=speed)
                )
            else:
                self.detail.setText(tr("{p0} MB · {p1}", p0=_mb(done), p1=speed))
        else:
            self.step.setText(tr("Preparing the update…"))
            self.detail.setText(tr("Unpacking files"))
        if not total:  # no Content-Length: a moving bar instead of a made-up share
            self.bar.setRange(0, 0)
            self.percent.setText("")
            return
        share = base + WEIGHT[step] * done / total
        self.bar.setRange(0, 100)
        self.bar.setValue(int(share * 100))
        self.percent.setText(f"{int(share * 100)}%")

    def _finished(self, result: object) -> None:
        self._running = False
        if self._stop.is_set() and isinstance(result, Path):  # cancelled after the last file
            updater.discard(result)
            result = updater.UpdateCancelled()
        if isinstance(result, updater.UpdateCancelled):
            self.cancelled.emit()
            super().reject()
            return
        if isinstance(result, Exception):
            for widget in (self.bar, self.percent, self.note):  # nothing is pending a restart
                widget.hide()
            self.step.setText(tr("Could not update: {p0}", p0=result))
            self.step.setWordWrap(True)
            self.detail.setText(tr("Nothing was installed. You can try again in Settings."))
            self.cancel_button.setText(tr("Close"))
            self.cancel_button.setEnabled(True)
            self.failed.emit(result)
            return
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.percent.setText("100%")
        self.step.setText(tr("Update ready. FocusLab restarts to finish it."))
        self.detail.setText("")
        self.cancel_button.setEnabled(False)
        QTimer.singleShot(READY_PAUSE_MS, lambda: self._hand_over(result))

    def _hand_over(self, staged: Path) -> None:
        self.accept()
        self.ready.emit(staged)

    # closing ----------------------------------------------------------------------------
    def reject(self) -> None:
        "Cancel (button, Esc or the close box): stop the worker, close once it has cleaned up."
        if not self._running:
            super().reject()
            return
        self._stop.set()
        self.cancel_button.setEnabled(False)
        self.step.setText(tr("Cancelling…"))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)

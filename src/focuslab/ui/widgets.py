"Reusable widgets: timelines, stacked bar charts, stat cards, state badge, camera preview."

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from html import escape

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import QFrame, QLabel, QToolTip, QVBoxLayout, QWidget

from focuslab.domain.events import StateSegment
from focuslab.domain.models import FocusState
from focuslab.focus.metrics import format_duration
from focuslab.focus.reasons import describe
from focuslab.i18n import tr, weekday_name
from focuslab.ui.theme import SHORT_LABELS, STATE_COLORS, STATE_LABELS


def clock_text(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def preview_label(text: str) -> QLabel:
    """Fixed-size dark box that shows the in-memory camera preview."""
    label = QLabel(text, alignment=Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(320, 240)
    label.setStyleSheet("background:#1F2430; color:#8C94A6; border-radius:8px;")
    return label


def frame_pixmap(frame: np.ndarray) -> QPixmap:
    """RGB preview frame to a pixmap; the copy detaches it from the numpy buffer."""
    h, w, _ = frame.shape
    image = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "-", hint: str = "", tag: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
        self._tag = QLabel(tag, objectName="CardTag")  # where the number comes from
        self._tag.setVisible(bool(tag))
        layout.addWidget(self._tag)
        self._title = QLabel(title, objectName="CardTitle")
        self._value = QLabel(value, objectName="CardValue")
        self._hint = QLabel(hint, objectName="CardHint")
        self._hint.setWordWrap(True)
        for w in (self._title, self._value, self._hint):
            layout.addWidget(w)

    def set(self, value: str, hint: str | None = None) -> None:
        self._value.setText(value)
        if hint is not None:
            self._hint.setText(hint)


class StateBadge(QLabel):
    def __init__(self) -> None:
        super().__init__(tr("Waiting"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(54)
        self.set_state(None)

    def set_state(self, state: FocusState | None, held: bool = False) -> None:
        color = STATE_COLORS[state] if state else "#E6E9EF"
        text = STATE_LABELS[state] if state else tr("Waiting")
        fg = "white" if state not in (None, FocusState.UNKNOWN) else "#3A4150"
        self.setText(text + (tr("  · Holding") if held else ""))
        self.setStyleSheet(
            f"background:{color}; color:{fg}; border-radius:12px; font-size:20px;"
            " font-weight:700; padding:10px 16px;"
        )


class Legend(QWidget):
    """Wrapping color labels, including longer English category names."""

    def __init__(self, items: Sequence[tuple[str, str]] | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if items is None:
            items = [(STATE_COLORS[s], SHORT_LABELS[s]) for s in FocusState]
        label = QLabel(objectName="Muted", wordWrap=True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(
            " &nbsp; ".join(
                f'<span style="color:{color}">●</span>&nbsp;{escape(text)}' for color, text in items
            )
        )
        label.setAccessibleName(" / ".join(text for _, text in items))
        layout.addWidget(label)


@dataclass(frozen=True)
class Bar:
    "One colored interval on a ``BarTimeline``; ``key`` is emitted when it is clicked."

    start: float
    end: float
    color: str
    key: object = None
    tooltip: str = ""
    marked: bool = False  # small triangle above the bar (e.g. corrected by the user)


class BarTimeline(QWidget):
    "Horizontal timeline of colored intervals over ``[start, end)`` with optional ticks."

    itemClicked = Signal(object)

    def __init__(self, height: int = 34) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self._bars: tuple[Bar, ...] = ()
        self._start, self._end = 0.0, 1.0
        self._selected: object = None
        self._ticks: tuple[tuple[float, str], ...] = ()

    def set_bars(
        self,
        bars: Sequence[Bar],
        start: float,
        end: float,
        selected: object = None,
        ticks: Sequence[tuple[float, str]] = (),
    ) -> None:
        self._bars = tuple(bars)
        self._start, self._end = start, max(end, start + 1)
        self._selected = selected
        self._ticks = tuple(ticks)
        self.update()

    def select(self, key: object) -> None:
        self._selected = key
        self.update()

    def _x(self, value: float) -> float:
        return (value - self._start) / (self._end - self._start) * self.width()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bottom = 18 if self._ticks else 6
        rect = QRectF(0, 6, self.width(), self.height() - 6 - bottom)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 6, 6)
        p.fillPath(clip, QColor("#EEF0F3"))
        p.setClipPath(clip)
        for bar in self._bars:
            x0, x1 = self._x(bar.start), self._x(bar.end)
            p.fillRect(QRectF(x0, rect.top(), max(1.0, x1 - x0), rect.height()), QColor(bar.color))
        p.setClipping(False)
        for bar in self._bars:
            x0, x1 = self._x(bar.start), self._x(bar.end)
            if bar.marked:
                p.setBrush(QColor("#1F2430"))
                p.setPen(Qt.PenStyle.NoPen)
                mid = (x0 + x1) / 2
                path = QPainterPath()
                path.moveTo(mid - 4, 0)
                path.lineTo(mid + 4, 0)
                path.lineTo(mid, 6)
                path.closeSubpath()
                p.drawPath(path)
            if self._selected is not None and bar.key == self._selected:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QColor("#1F2430"))
                p.drawRect(QRectF(x0, rect.top(), max(2.0, x1 - x0), rect.height()))
        p.setPen(QColor("#6B7385"))
        for value, text in self._ticks:
            x = self._x(value)
            p.drawLine(int(x), int(rect.bottom()), int(x), int(rect.bottom()) + 3)
            left = min(max(0.0, x - 30), self.width() - 60.0)  # keep edge labels visible
            p.drawText(QRectF(left, rect.bottom() + 2, 60, 14), Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def bar_at(self, x: float) -> Bar | None:
        value = self._start + x / max(1, self.width()) * (self._end - self._start)
        for bar in self._bars:
            if bar.start <= value < bar.end:
                return bar
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        bar = self.bar_at(event.position().x())
        if bar is None or not bar.tooltip:
            QToolTip.hideText()
            return
        QToolTip.showText(event.globalPosition().toPoint(), bar.tooltip, self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        bar = self.bar_at(event.position().x())
        if bar is not None:
            self.itemClicked.emit(bar.key)


def _segment_tooltip(seg: StateSegment) -> str:
    lines = [
        f"{clock_text(seg.start_s)}–{clock_text(seg.end_s)} ({format_duration(seg.duration_s)})",
        STATE_LABELS[seg.state],
    ]
    if seg.corrected_label:
        lines.append(tr("Corrected → {p0}", p0=STATE_LABELS[seg.corrected_label]))
    lines += [f"· {text}" for text in describe(seg.reason_codes)]
    if seg.app_names:
        lines.append(tr("Apps: ") + ", ".join(seg.app_names))
    return "\n".join(lines)


class TimelineWidget(BarTimeline):
    """State timeline of a focus session. Corrected segments show the corrected state."""

    segmentClicked = Signal(object)  # StateSegment

    def __init__(self, height: int = 34) -> None:
        super().__init__(height)
        self.itemClicked.connect(self.segmentClicked)

    def set_segments(
        self,
        segments: Sequence[StateSegment],
        total_s: int | None = None,
        selected_event: int | None = None,
    ) -> None:
        bars = [
            Bar(
                seg.start_s,
                seg.end_s,
                STATE_COLORS[seg.effective_state],
                seg,
                _segment_tooltip(seg),
                bool(seg.corrected_label),
            )
            for seg in segments
        ]
        end = segments[-1].end_s if segments else 0
        selected = next((s for s in segments if s.event_id == selected_event), None)
        self.set_bars(bars, 0, max(1, total_s or 0, end), selected)


class StackedBars(QWidget):
    "Vertical stacked bars: one column per label, stacked in ``order`` with ``colors``."

    def __init__(
        self,
        order: Sequence[object],
        colors: Mapping[object, str],
        value_text: Callable[[float], str] = lambda seconds: tr("{p0}m", p0=round(seconds / 60)),
        label_every: int = 1,
        height: int = 150,
    ) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self._order, self._colors = tuple(order), dict(colors)
        self._value_text, self.label_every = value_text, label_every
        self._columns: list[tuple[str, Mapping[object, float]]] = []

    def set_columns(self, columns: Sequence[tuple[str, Mapping[object, float]]]) -> None:
        self._columns = list(columns)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._columns:
            p.end()
            return
        top, bottom_pad = 18, 22
        h = self.height() - top - bottom_pad
        peak = max((sum(c.values()) for _, c in self._columns), default=0) or 1
        slot = self.width() / len(self._columns)
        bar_w = min(38.0, slot * 0.55)
        p.setPen(QColor("#6B7385"))
        for i, (label, values) in enumerate(self._columns):
            x = i * slot + (slot - bar_w) / 2
            y = top + h
            for key in self._order:
                value = values.get(key, 0)
                if not value:
                    continue
                bar_h = value / peak * h
                y -= bar_h
                p.fillRect(QRectF(x, y, bar_w, bar_h), QColor(self._colors[key]))
            if i % self.label_every == 0:
                p.drawText(
                    QRectF(i * slot - slot, top + h + 4, slot * 3, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )
            total = sum(values.values())
            if total and self.label_every == 1:
                p.drawText(
                    QRectF(i * slot, y - 16, slot, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    self._value_text(total),
                )
        p.end()


class WeekChart(StackedBars):
    """Stacked minutes per focus state for each day."""

    def __init__(self) -> None:
        super().__init__(list(FocusState), STATE_COLORS)

    def set_days(self, days: list[tuple[date, Counter[FocusState]]]) -> None:
        self.set_columns(
            [(f"{d.month}/{d.day}({weekday_name(d.weekday())})", counts) for d, counts in days]
        )

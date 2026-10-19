"""Reusable widgets: state timeline, weekly chart, stat cards, state badge, camera preview."""

from collections import Counter
from collections.abc import Sequence
from datetime import date

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
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolTip, QVBoxLayout, QWidget

from focuslab.domain.events import StateSegment
from focuslab.domain.models import FocusState
from focuslab.focus.metrics import format_duration
from focuslab.focus.reasons import describe
from focuslab.ui.theme import SHORT_LABELS, STATE_COLORS, STATE_LABELS

_WEEKDAYS = "월화수목금토일"


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
    def __init__(self, title: str, value: str = "-", hint: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(2)
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
        super().__init__("대기 중")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(54)
        self.set_state(None)

    def set_state(self, state: FocusState | None, held: bool = False) -> None:
        color = STATE_COLORS[state] if state else "#E6E9EF"
        text = STATE_LABELS[state] if state else "대기 중"
        fg = "white" if state not in (None, FocusState.UNKNOWN) else "#3A4150"
        self.setText(text + ("  · 유지 중" if held else ""))
        self.setStyleSheet(
            f"background:{color}; color:{fg}; border-radius:12px; font-size:20px;"
            " font-weight:700; padding:10px 16px;"
        )


class Legend(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for state in FocusState:
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{STATE_COLORS[state]}; border-radius:5px;")
            layout.addWidget(dot)
            label = QLabel(SHORT_LABELS[state], objectName="Muted")
            layout.addWidget(label)
        layout.addStretch()


class TimelineWidget(QWidget):
    """Horizontal state timeline. Corrected segments show the corrected state and a marker."""

    segmentClicked = Signal(object)  # StateSegment

    def __init__(self, height: int = 34) -> None:
        super().__init__()
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self._segments: tuple[StateSegment, ...] = ()
        self._total = 1
        self._selected: int | None = None

    def set_segments(
        self, segments: Sequence[StateSegment], total_s: int | None = None,
        selected_event: int | None = None,
    ) -> None:
        self._segments = tuple(segments)
        end = self._segments[-1].end_s if self._segments else 0
        self._total = max(1, total_s or 0, end)
        self._selected = selected_event
        self.update()

    def _x(self, seconds: float) -> float:
        return seconds / self._total * self.width()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 6, self.width(), self.height() - 12)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 6, 6)
        p.fillPath(clip, QColor("#EEF0F3"))
        p.setClipPath(clip)
        for seg in self._segments:
            x0, x1 = self._x(seg.start_s), self._x(seg.end_s)
            p.fillRect(QRectF(x0, rect.top(), max(1.0, x1 - x0), rect.height()),
                       QColor(STATE_COLORS[seg.effective_state]))
        p.setClipping(False)
        for seg in self._segments:
            x0, x1 = self._x(seg.start_s), self._x(seg.end_s)
            if seg.corrected_label:
                p.setBrush(QColor("#1F2430"))
                p.setPen(Qt.PenStyle.NoPen)
                mid = (x0 + x1) / 2
                path = QPainterPath()
                path.moveTo(mid - 4, 0)
                path.lineTo(mid + 4, 0)
                path.lineTo(mid, 6)
                path.closeSubpath()
                p.drawPath(path)
            if self._selected is not None and seg.event_id == self._selected:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QColor("#1F2430"))
                p.drawRect(QRectF(x0, rect.top(), max(2.0, x1 - x0), rect.height()))
        p.end()

    def _segment_at(self, x: float) -> StateSegment | None:
        seconds = x / max(1, self.width()) * self._total
        for seg in self._segments:
            if seg.start_s <= seconds < seg.end_s:
                return seg
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        seg = self._segment_at(event.position().x())
        if seg is None:
            QToolTip.hideText()
            return
        lines = [
            f"{clock_text(seg.start_s)}–{clock_text(seg.end_s)}"
            f" ({format_duration(seg.duration_s)})",
            STATE_LABELS[seg.state],
        ]
        if seg.corrected_label:
            lines.append(f"정정됨 → {STATE_LABELS[seg.corrected_label]}")
        lines += [f"· {text}" for text in describe(seg.reason_codes)]
        if seg.app_names:
            lines.append("앱: " + ", ".join(seg.app_names))
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        seg = self._segment_at(event.position().x())
        if seg is not None:
            self.segmentClicked.emit(seg)


class WeekChart(QWidget):
    """Stacked minutes per state for each day."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self._days: list[tuple[date, Counter[FocusState]]] = []

    def set_days(self, days: list[tuple[date, Counter[FocusState]]]) -> None:
        self._days = days
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._days:
            p.end()
            return
        top, bottom_pad = 18, 22
        h = self.height() - top - bottom_pad
        peak = max((sum(c.values()) for _, c in self._days), default=0) or 1
        slot = self.width() / len(self._days)
        bar_w = min(38.0, slot * 0.55)
        p.setPen(QColor("#6B7385"))
        for i, (day, counts) in enumerate(self._days):
            x = i * slot + (slot - bar_w) / 2
            y = top + h
            for state in FocusState:
                seconds = counts.get(state, 0)
                if not seconds:
                    continue
                bar_h = seconds / peak * h
                y -= bar_h
                p.fillRect(QRectF(x, y, bar_w, bar_h), QColor(STATE_COLORS[state]))
            total = sum(counts.values())
            label_rect = QRectF(i * slot, top + h + 4, slot, 16)
            p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter,
                       f"{day.month}/{day.day}({_WEEKDAYS[day.weekday()]})")
            if total:
                p.drawText(QRectF(i * slot, y - 16, slot, 14), Qt.AlignmentFlag.AlignCenter,
                           f"{round(total / 60)}분")
        p.end()

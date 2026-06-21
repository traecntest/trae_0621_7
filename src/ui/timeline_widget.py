"""Draggable timeline widget with event markers.

Renders a horizontal track spanning the match duration, places category-coded
markers for each event and lets the user drag the playhead or click to jump.
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QMouseEvent, QPaintEvent, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from ..core.models import EventCategory, GameEvent

_CATEGORY_COLORS = {
    EventCategory.TEAMFIGHT: QColor("#e53935"),
    EventCategory.LANING: QColor("#1e88e5"),
    EventCategory.RESOURCE_CONTROL: QColor("#fb8c00"),
    EventCategory.OBJECTIVE: QColor("#8e24aa"),
    EventCategory.ROAMING: QColor("#00897b"),
    EventCategory.GENERAL: QColor("#9e9e9e"),
}

_TRACK_H = 36
_MARGIN = 16


class TimelineWidget(QWidget):
    """Interactive timeline with event markers and a draggable playhead."""

    positionChanged = pyqtSignal(float)
    eventClicked = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self._duration = 0.0
        self._events: List[GameEvent] = []
        self._position = 0.0
        self._dragging = False
        self._hover_idx: Optional[int] = None

    def set_data(self, duration: float, events: List[GameEvent]) -> None:
        self._duration = max(1.0, duration)
        self._events = sorted(events, key=lambda e: e.timestamp)
        self._position = min(self._position, self._duration)
        self.update()

    def set_position(self, seconds: float) -> None:
        self._position = max(0.0, min(seconds, self._duration))
        self.update()

    # ----------------------------------------------------------------- paint
    def _track_rect(self):
        return self._MARGIN_RECT()

    def _MARGIN_RECT(self):
        w = self.width() - 2 * _MARGIN
        return _MARGIN, 30, w, _TRACK_H

    def _x_for_time(self, seconds: float) -> float:
        _, _, w, _ = self._MARGIN_RECT()
        ratio = seconds / self._duration if self._duration else 0
        return _MARGIN + ratio * w

    def _time_for_x(self, x: float) -> float:
        _, _, w, _ = self._MARGIN_RECT()
        ratio = max(0.0, min(1.0, (x - _MARGIN) / w))
        return ratio * self._duration

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        x, y, w, h = self._MARGIN_RECT()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2a2d36"))
        painter.drawRoundedRect(int(x), int(y), int(w), int(h), 6, 6)

        for i, ev in enumerate(self._events):
            ex = self._x_for_time(ev.timestamp)
            color = _CATEGORY_COLORS.get(ev.category, QColor("#9e9e9e"))
            painter.setBrush(color)
            pen = QPen(QColor("#fff")) if i == self._hover_idx else QPen(color.darker(150))
            pen.setWidthF(1.2)
            painter.setPen(pen)
            painter.drawEllipse(int(ex - 6), int(y - 6), 12, 12)

        px = self._x_for_time(self._position)
        painter.setPen(QPen(QColor("#4caf50"), 2))
        painter.drawLine(int(px), int(y - 10), int(px), int(y + h + 10))

        painter.setPen(QColor("#bdbdbd"))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(int(x), int(y + h + 28), f"00:00")
        end_label = f"{int(self._duration)//60:02d}:{int(self._duration)%60:02d}"
        painter.drawText(int(x + w - 32), int(y + h + 28), end_label)

        if self._hover_idx is not None and 0 <= self._hover_idx < len(self._events):
            ev = self._events[self._hover_idx]
            tip = f"{int(ev.timestamp)//60:02d}:{int(ev.timestamp)%60:02d}  {ev.title}"
            painter.setPen(QColor("#e6e6e6"))
            painter.drawText(int(x), 18, tip)

    # ----------------------------------------------------------------- mouse
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        x = event.x()
        hit = self._event_at(x)
        if hit is not None:
            self.eventClicked.emit(self._events[hit])
            self.set_position(self._events[hit].timestamp)
            self.positionChanged.emit(self._events[hit].timestamp)
            return
        self._dragging = True
        self._apply_x(x)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        x = event.x()
        if self._dragging:
            self._apply_x(x)
        else:
            idx = self._event_at(x)
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.update()
            self.setCursor(Qt.PointingHandCursor if idx is not None else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False

    def _apply_x(self, x: float) -> None:
        t = self._time_for_x(x)
        self.set_position(t)
        self.positionChanged.emit(t)

    def _event_at(self, x: float) -> Optional[int]:
        for i, ev in enumerate(self._events):
            if abs(self._x_for_time(ev.timestamp) - x) <= 8:
                return i
        return None

"""Video / frame viewer with operation heat-zone overlay.

Displays the current frame image and, when available, overlays hero positions
and a translucent heat-zone marker so the user can correlate the timeline with
what is happening on screen.
"""

from __future__ import annotations

import os
from typing import List, Optional

import cv2
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.models import FrameState, GameEvent


class VideoPlayerWidget(QWidget):
    """Frame display + overlay canvas."""

    positionRequested = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background-color:#000; border-radius:8px;")
        self._label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._label.setMinimumHeight(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        self._qimage: Optional[QImage] = None
        self._frame_state: Optional[FrameState] = None
        self._events: List[GameEvent] = []
        self._show_heatmap = True

    def show_frame(self, path: Optional[str], state: Optional[FrameState] = None) -> None:
        self._frame_state = state
        if path and os.path.isfile(path):
            img = cv2.imread(path)
            if img is not None:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h, w, ch = img.shape
                self._qimage = QImage(img.data, w, h, ch * w, QImage.Format_RGB888).copy()
            else:
                self._qimage = None
        else:
            self._qimage = None
        self.update()

    def set_events(self, events: List[GameEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.timestamp)
        self.update()

    def toggle_heatmap(self, on: bool) -> None:
        self._show_heatmap = on
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self._qimage is not None:
            scaled = self._qimage.scaled(
                self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._label.setPixmap(QPixmap.fromImage(scaled))
        else:
            self._label.setText("暂无画面\n请选择对局并播放或拖动时间轴")
            self._label.setStyleSheet("color:#888; background-color:#000; border-radius:8px;")
        painter.end()

        if self._show_heatmap and self._frame_state and self._frame_state.hero_positions:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            lw = max(1, self._label.width())
            lh = max(1, self._label.height())
            ox = (self.width() - lw) // 2
            oy = (self.height() - lh) // 2
            for hero in self._frame_state.hero_positions:
                hx = int(ox + (hero.x / 1280.0) * lw)
                hy = int(oy + (hero.y / 720.0) * lh)
                color = QColor("#4caf50") if hero.team == "ally" else QColor("#e53935")
                painter.setPen(QPen(color, 2))
                painter.setBrush(QColor(color.red(), color.green(), color.blue(), 60))
                painter.drawEllipse(hx - 8, hy - 8, 16, 16)
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._qimage is not None and self._frame_state:
            self.positionRequested.emit(self._frame_state.timestamp)

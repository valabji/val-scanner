"""Sparkline: amber gradient line graph for throughput history.

Ring buffer of N samples (default 60); paints a gradient-filled QPainterPath
stroked in ACCENT. Used by the Process Monitor "Throughput · 60s" section.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QPainter, QPainterPath, QLinearGradient, QColor, QPen,
)
from PySide6.QtWidgets import QWidget

from ..constants import ACCENT, DARK_BG


class Sparkline(QWidget):
    """Fixed-height (40px) gradient sparkline.

    Append samples via ``add_sample(float)``; the widget keeps the last
    ``capacity`` values and repaints on each append. If no samples have been
    pushed yet, paints an empty background.
    """

    def __init__(self, capacity: int = 60, parent=None) -> None:
        super().__init__(parent)
        self._capacity = capacity
        self._samples: Deque[float] = deque(maxlen=capacity)
        self.setFixedHeight(40)
        self.setMinimumWidth(60)

    def add_sample(self, value: float) -> None:
        """Append a sample (must be >= 0). Triggers repaint."""
        self._samples.append(max(0.0, float(value)))
        self.update()

    def clear(self) -> None:
        """Drop all samples."""
        self._samples.clear()
        self.update()

    def sample_count(self) -> int:
        return len(self._samples)

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        n = len(self._samples)
        if n < 2:
            # Nothing meaningful to draw yet
            return

        peak = max(self._samples) or 1.0
        pad = 4
        usable_h = h - pad * 2

        # Build the line path
        path = QPainterPath()
        for i, v in enumerate(self._samples):
            t = i / (n - 1)
            x = t * w
            y = h - pad - (v / peak) * usable_h
            if i == 0:
                path.moveTo(QPointF(x, y))
            else:
                path.lineTo(QPointF(x, y))

        # Build area path (line + close to baseline)
        area = QPainterPath(path)
        area.lineTo(QPointF(w, h))
        area.lineTo(QPointF(0, h))
        area.closeSubpath()

        # Gradient fill
        acc = QColor(str(ACCENT))
        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(acc); top.setAlphaF(0.40)
        bot = QColor(acc); bot.setAlphaF(0.0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.fillPath(area, grad)

        # Stroke the line
        pen = QPen(acc)
        pen.setWidthF(1.2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawPath(path)
        p.end()

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

from ..constants import CATEGORY_COLORS, PANEL_BG, BORDER, SUBTEXT

BAR_H    = 40
LEGEND_H = 36


class _StackBar(QWidget):
    """Draws a single horizontal stacked bar from {category: bytes} data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(BAR_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._segments: list[tuple[str, float]] = []  # (color_hex, fraction)

    def set_segments(self, segments: list[tuple[str, float]]) -> None:
        self._segments = segments
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()

        if not self._segments:
            painter.fillRect(0, 0, w, h, QColor(str(PANEL_BG)))
            painter.end()
            return

        x = 0
        for i, (color, frac) in enumerate(self._segments):
            seg_w = int(frac * w)
            if i == len(self._segments) - 1:
                seg_w = w - x  # absorb rounding remainder
            if seg_w > 0:
                painter.fillRect(x, 0, seg_w, h, QColor(color))
            x += seg_w

        painter.end()


class VolumeMapWidget(QWidget):
    """Stacked-bar volume map: 40px bar + 36px legend, driven by set_data()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(BAR_H + LEGEND_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(f"background: {PANEL_BG}; border-top: 1px solid {BORDER};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._bar = _StackBar()
        lay.addWidget(self._bar)

        self._legend_row = QWidget()
        self._legend_row.setFixedHeight(LEGEND_H)
        self._legend_lay = QHBoxLayout(self._legend_row)
        self._legend_lay.setContentsMargins(8, 4, 8, 4)
        self._legend_lay.setSpacing(10)
        self._legend_lay.addStretch()
        lay.addWidget(self._legend_row)

        self._data: dict[str, int] = {}

    def set_data(self, data: dict[str, int]) -> None:
        """Update the widget with {category: size_bytes} mapping."""
        self._data = {k: v for k, v in data.items() if v > 0}
        self._rebuild()

    def _rebuild(self) -> None:
        total = sum(self._data.values()) or 1

        # Sort by size descending; limit to top 8 for readability
        ranked = sorted(self._data.items(), key=lambda x: x[1], reverse=True)[:8]

        segments: list[tuple[str, float]] = []
        for cat, nbytes in ranked:
            color = CATEGORY_COLORS.get(cat, "#808080")
            segments.append((color, nbytes / total))

        # Remaining categories collapsed into one grey segment
        shown_bytes = sum(b for _, b in ranked)
        rest = total - shown_bytes
        if rest > 0:
            segments.append(("#404040", rest / total))

        self._bar.set_segments(segments)
        self._rebuild_legend(ranked, total)

    def _rebuild_legend(self, ranked: list[tuple[str, int]], total: int) -> None:
        while self._legend_lay.count():
            item = self._legend_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for cat, nbytes in ranked[:6]:  # max 6 legend entries
            color = CATEGORY_COLORS.get(cat, "#808080")
            pct   = nbytes * 100 / total

            chip = QWidget()
            chip.setFixedSize(8, 8)
            chip.setStyleSheet(
                f"background: {color}; border-radius: 4px; border: none;"
            )
            lbl = QLabel(f"{cat}  {pct:.0f}%")
            lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 10px; background: transparent;")

            pair = QWidget()
            pair_lay = QHBoxLayout(pair)
            pair_lay.setContentsMargins(0, 0, 0, 0)
            pair_lay.setSpacing(4)
            pair_lay.addWidget(chip, 0, Qt.AlignVCenter)
            pair_lay.addWidget(lbl,  0, Qt.AlignVCenter)
            self._legend_lay.addWidget(pair)

        self._legend_lay.addStretch()

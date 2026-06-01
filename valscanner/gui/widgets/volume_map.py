from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QPushButton, QScrollArea

from ..constants import CATEGORY_COLORS, PANEL_BG, BORDER, SUBTEXT, TEXT
from .. import icons as _icons
from ..theme import Spacing, Margins, Sizes

BAR_H    = 40
LEGEND_H = 36
MIN_HEIGHT = 80
MAX_HEIGHT = 300


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
    """Resizable, scrollable, collapsible stacked-bar volume map."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(MIN_HEIGHT)
        self.setMaximumHeight(MAX_HEIGHT)
        self.setStyleSheet(f"background: {PANEL_BG}; border-top: 1px solid {BORDER};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*Margins.NONE)
        lay.setSpacing(Spacing.NONE)

        # Header with title and collapse button
        hdr = QWidget()
        hdr.setFixedHeight(Sizes.HEADER_H_SM)
        hdr.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 1px solid {BORDER};")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(Spacing.SM, Spacing.NONE, Spacing.SM, Spacing.NONE)
        hdr_lay.setSpacing(Spacing.PX6)

        title = QLabel("Volume Distribution")
        title.setStyleSheet(f"color: {TEXT}; font-size: 10px; font-weight: bold; background: transparent;")
        hdr_lay.addWidget(title)
        hdr_lay.addStretch()

        self._collapse_btn = QPushButton()
        self._collapse_btn.setIcon(_icons.icon("mdi.chevron-down", color=str(TEXT)))
        self._collapse_btn.setIconSize(QSize(14, 14))
        self._collapse_btn.setFixedSize(22, 22)
        self._collapse_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;}}"
            f"QPushButton:hover{{background:{BORDER};border-radius:4px;}}"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        hdr_lay.addWidget(self._collapse_btn)
        lay.addWidget(hdr)

        # Content area
        self._content = QWidget()
        content_lay = QVBoxLayout(self._content)
        content_lay.setContentsMargins(*Margins.NONE)
        content_lay.setSpacing(Spacing.NONE)

        self._bar = _StackBar()
        content_lay.addWidget(self._bar)

        # Scrollable legend
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: transparent; }}")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._legend_row = QWidget()
        self._legend_lay = QVBoxLayout(self._legend_row)
        self._legend_lay.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
        self._legend_lay.setSpacing(Spacing.XS)
        self._legend_lay.addStretch()
        scroll.setWidget(self._legend_row)
        content_lay.addWidget(scroll)

        lay.addWidget(self._content)

        self._data: dict[str, int] = {}
        self._collapsed = False

    def _toggle_collapse(self) -> None:
        """Toggle content visibility."""
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        icon_name = "mdi.chevron-right" if self._collapsed else "mdi.chevron-down"
        self._collapse_btn.setIcon(_icons.icon(icon_name, color=str(TEXT)))

        if self._collapsed:
            self.setMinimumHeight(32)  # Just header
            self.setMaximumHeight(32)
        else:
            self.setMinimumHeight(MIN_HEIGHT)
            self.setMaximumHeight(MAX_HEIGHT)

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

        for cat, nbytes in ranked:  # show all ranked entries (scrollable)
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
            pair_lay.setContentsMargins(*Margins.NONE)
            pair_lay.setSpacing(Spacing.XS)
            pair_lay.addWidget(chip, 0, Qt.AlignVCenter)
            pair_lay.addWidget(lbl,  0, Qt.AlignVCenter)
            self._legend_lay.addWidget(pair)

        self._legend_lay.addStretch()

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
)

from .constants import PANEL_BG, BORDER, SUBTEXT, ACCENT

RAIL_W = 28


class VerticalLabel(QLabel):
    """QLabel whose text is drawn rotated 90° (reads top-to-bottom)."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(), Qt.AlignCenter, self.text())
        painter.end()

    def sizeHint(self) -> QSize:
        h = super().sizeHint()
        return QSize(h.height(), h.width())


class CollapsiblePanel(QWidget):
    """Wraps a content widget with a 28-px collapsible edge rail."""

    RAIL_W  = RAIL_W
    toggled = Signal(bool)   # True = expanded

    def __init__(self, title: str, content: QWidget,
                 border_side: str = "right", parent=None):
        super().__init__(parent)
        self._title       = title
        self._content     = content
        self._expanded    = True
        self._border_side = border_side

        # Rail shown when collapsed
        self._rail = QWidget()
        self._rail.setFixedWidth(RAIL_W)
        self._rail_lay = QVBoxLayout(self._rail)
        self._rail_lay.setContentsMargins(0, 4, 0, 4)
        self._rail_lay.setSpacing(0)

        self._toggle_btn = QPushButton("›")
        self._toggle_btn.setFixedSize(RAIL_W, RAIL_W)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.clicked.connect(lambda: self.set_expanded(True))
        self._rail_lay.addWidget(self._toggle_btn)

        self._rail_label = VerticalLabel(title)
        self._rail_lay.addWidget(self._rail_label, 1)

        self._rail.hide()
        self.apply_theme()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._rail)
        lay.addWidget(self._content, 1)

    # ── public ────────────────────────────────────────────────────────────────

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._rail.setVisible(not expanded)
        if expanded:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
        else:
            self.setFixedWidth(RAIL_W)
        self.toggled.emit(expanded)

    def apply_theme(self) -> None:
        self._rail.setStyleSheet(
            f"background: {PANEL_BG};"
            f" border-{self._border_side}: 1px solid {BORDER};"
        )
        self._toggle_btn.setStyleSheet(
            f"QPushButton{{color:{SUBTEXT};font-size:14px;border:none;"
            f"background:transparent;padding:0;}}"
            f"QPushButton:hover{{color:{ACCENT};}}"
        )
        self._rail_label.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 11px; background: transparent;"
        )

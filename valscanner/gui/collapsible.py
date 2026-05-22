from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QFont, QPainter, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from .constants import PANEL_BG, BORDER, SUBTEXT, ACCENT, BG2, DIVIDER2
from . import icons as _icons

RAIL_W = 28


class _ClickWidget(QWidget):
    """QWidget that emits a clicked() signal on mouse release."""

    from PySide6.QtCore import Signal as _Signal  # noqa: E402
    clicked = _Signal()

    def mouseReleaseEvent(self, ev: "QMouseEvent") -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)

    def enterEvent(self, ev: QEvent) -> None:
        self.setProperty("hover", True)
        self.style().unpolish(self); self.style().polish(self)
        super().enterEvent(ev)

    def leaveEvent(self, ev: QEvent) -> None:
        self.setProperty("hover", False)
        self.style().unpolish(self); self.style().polish(self)
        super().leaveEvent(ev)


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
    """Wraps a content widget with a 28-px collapsible edge rail.

    The rail (visible when collapsed) shows three stacked elements top-to-bottom:
    a chevron pointing into the panel, a small icon, then a vertical label.
    The whole rail is one big clickable surface that re-expands the panel.
    """

    RAIL_W  = RAIL_W
    toggled = Signal(bool)   # True = expanded

    def __init__(self, title: str, content: QWidget,
                 border_side: str = "right", icon_name: str | None = None,
                 parent=None):
        super().__init__(parent)
        self._title       = title
        self._content     = content
        self._expanded    = True
        self._border_side = border_side
        self._icon_name   = icon_name

        # Rail shown when collapsed — entirely click-through to re-expand.
        self._rail = _ClickWidget()
        self._rail.setFixedWidth(RAIL_W)
        self._rail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._rail.setCursor(Qt.PointingHandCursor)
        self._rail.clicked.connect(lambda: self.set_expanded(True))

        self._rail_lay = QVBoxLayout(self._rail)
        self._rail_lay.setContentsMargins(0, 4, 0, 4)
        self._rail_lay.setSpacing(0)

        # Chevron pointing into the panel — direction depends on which side the
        # rail lives on. border_side="right" → rail is on the LEFT of content
        # → chevron should point right (›). border_side="left" → rail is on the
        # RIGHT → chevron points left (‹).
        chev = "›" if border_side == "right" else "‹"
        self._chev_lbl = QLabel(chev)
        self._chev_lbl.setFixedHeight(28)
        self._chev_lbl.setAlignment(Qt.AlignCenter)
        self._rail_lay.addWidget(self._chev_lbl)

        # Small icon at top
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedHeight(26)
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        if icon_name:
            self._icon_lbl.setPixmap(_icons.pixmap(icon_name, 14, color=str(SUBTEXT)))
        self._rail_lay.addWidget(self._icon_lbl)

        self._rail_label = VerticalLabel(title.upper())
        font = self._rail_label.font()
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self._rail_label.setFont(font)
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
            f"_ClickWidget{{background:{PANEL_BG};"
            f"border:0;border-{self._border_side}:1px solid {BORDER};}}"
            f"_ClickWidget[hover='true']{{background:{BG2};}}"
        )
        self._chev_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 14px; font-weight: 500; background: transparent;"
            f"border-bottom: 1px solid {BORDER};"
        )
        self._icon_lbl.setStyleSheet(
            f"background: transparent;"
            f"border-bottom: 1px solid {BORDER};"
        )
        if self._icon_name:
            self._icon_lbl.setPixmap(_icons.pixmap(self._icon_name, 14, color=str(SUBTEXT)))
        self._rail_label.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: transparent;"
            f"font-family: 'JetBrains Mono', monospace;"
        )

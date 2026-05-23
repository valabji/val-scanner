from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QFont, QPainter, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QSplitter,
)

from .constants import PANEL_BG, BORDER, SUBTEXT, ACCENT, BG2, DIVIDER2
from . import icons as _icons

RAIL_W  = 28
_BTN_SZ = 20


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

    The collapse button is exposed via self.collapse_button so callers can
    inject it into the content panel's own header rather than adding a
    duplicate header bar here.
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

        # border_side="right" → rail on LEFT → chevron points right (›)
        # border_side="left"  → rail on RIGHT → chevron points left (‹)
        chev_expand = "›" if border_side == "right" else "‹"
        self._chev_lbl = QLabel(chev_expand)
        self._chev_lbl.setFixedHeight(28)
        self._chev_lbl.setAlignment(Qt.AlignCenter)
        self._rail_lay.addWidget(self._chev_lbl)

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

        # Collapse button — NOT placed in a layout here; callers inject it
        # into the content panel's existing header via self.collapse_button.
        chev_collapse = "‹" if border_side == "right" else "›"
        self.collapse_button = QPushButton(chev_collapse)
        self.collapse_button.setFixedSize(_BTN_SZ, _BTN_SZ)
        self.collapse_button.setCursor(Qt.PointingHandCursor)
        self.collapse_button.setToolTip("Collapse panel")
        self.collapse_button.clicked.connect(lambda: self.set_expanded(False))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._rail)
        lay.addWidget(self._content, 1)

        self.apply_theme()

    # ── public ────────────────────────────────────────────────────────────────

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._rail.setVisible(not expanded)
        self.collapse_button.setVisible(expanded)
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
        self.collapse_button.setStyleSheet(
            f"QPushButton{{"
            f"  background: transparent; border: none;"
            f"  color: {SUBTEXT}; font-size: 13px; font-weight: 500;"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover{{"
            f"  background: {BG2}; color: {ACCENT};"
            f"}}"
        )


# ── Right-zone helpers ────────────────────────────────────────────────────────


class _StackedRail(QWidget):
    """28-px rail with two stacked halves — shown when both Inspector and Monitor
    are collapsed simultaneously."""

    inspector_clicked = Signal()
    monitor_clicked   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(RAIL_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._insp_half = _ClickWidget()
        self._insp_half.setCursor(Qt.PointingHandCursor)
        self._insp_half.setFixedWidth(RAIL_W)
        self._insp_half.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._insp_half.clicked.connect(self.inspector_clicked)
        ih = QVBoxLayout(self._insp_half)
        ih.setContentsMargins(0, 4, 0, 4)
        ih.setSpacing(0)
        self._insp_chev = QLabel("›")
        self._insp_chev.setFixedHeight(28)
        self._insp_chev.setAlignment(Qt.AlignCenter)
        ih.addWidget(self._insp_chev)
        self._insp_icon = QLabel()
        self._insp_icon.setFixedHeight(26)
        self._insp_icon.setAlignment(Qt.AlignCenter)
        ih.addWidget(self._insp_icon)
        self._insp_lbl = VerticalLabel("INSPECTOR")
        f = self._insp_lbl.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self._insp_lbl.setFont(f)
        ih.addWidget(self._insp_lbl, 1)
        outer.addWidget(self._insp_half, 1)

        # Thin divider between the two halves
        self._div = QWidget()
        self._div.setFixedHeight(1)
        outer.addWidget(self._div)

        self._mon_half = _ClickWidget()
        self._mon_half.setCursor(Qt.PointingHandCursor)
        self._mon_half.setFixedWidth(RAIL_W)
        self._mon_half.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._mon_half.clicked.connect(self.monitor_clicked)
        mh = QVBoxLayout(self._mon_half)
        mh.setContentsMargins(0, 4, 0, 4)
        mh.setSpacing(0)
        self._mon_chev = QLabel("›")
        self._mon_chev.setFixedHeight(28)
        self._mon_chev.setAlignment(Qt.AlignCenter)
        mh.addWidget(self._mon_chev)
        self._mon_icon = QLabel()
        self._mon_icon.setFixedHeight(26)
        self._mon_icon.setAlignment(Qt.AlignCenter)
        mh.addWidget(self._mon_icon)
        self._mon_lbl = VerticalLabel("MONITOR")
        f = self._mon_lbl.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self._mon_lbl.setFont(f)
        mh.addWidget(self._mon_lbl, 1)
        outer.addWidget(self._mon_half, 1)

        self.apply_theme()

    def apply_theme(self) -> None:
        self.setStyleSheet(
            f"background:{PANEL_BG}; border-left:1px solid {BORDER};"
        )
        self._div.setStyleSheet(f"background:{BORDER};")
        _rail_ss = (
            f"_ClickWidget{{background:transparent; border:none;}}"
            f"_ClickWidget[hover='true']{{background:{BG2};}}"
        )
        _chev_ss = (
            f"color:{SUBTEXT}; font-size:14px; font-weight:500; background:transparent;"
            f"border-bottom:1px solid {BORDER};"
        )
        _icon_ss = f"background:transparent; border-bottom:1px solid {BORDER};"
        _lbl_ss  = (
            f"color:{SUBTEXT}; font-size:10px; background:transparent;"
            f"font-family:'JetBrains Mono',monospace;"
        )
        for half in (self._insp_half, self._mon_half):
            half.setStyleSheet(_rail_ss)
        for chev in (self._insp_chev, self._mon_chev):
            chev.setStyleSheet(_chev_ss)
        for ico in (self._insp_icon, self._mon_icon):
            ico.setStyleSheet(_icon_ss)
        for lbl in (self._insp_lbl, self._mon_lbl):
            lbl.setStyleSheet(_lbl_ss)
        self._insp_icon.setPixmap(_icons.pixmap("mdi.eye-outline", 14, color=str(SUBTEXT)))
        self._mon_icon.setPixmap(_icons.pixmap("mdi.pulse",        14, color=str(SUBTEXT)))


class RightZone(QWidget):
    """The right zone of the main window: Inspector + Monitor with 4-state model.

    States (based on which panels are visible):
      both    — side-by-side via inner splitter
      insp    — inspector content + monitor single-rail (28 px)
      mon     — inspector single-rail (28 px) + monitor content
      neither — single stacked-rail (28 px)
    """

    inspector_toggled = Signal(bool)
    monitor_toggled   = Signal(bool)

    def __init__(self, inspector: QWidget, monitor: QWidget, parent=None):
        super().__init__(parent)
        self._inspector = inspector
        self._monitor   = monitor
        self._insp_vis  = True
        self._mon_vis   = True

        # Single rails — shown when one panel is collapsed and the other is not
        self._insp_rail = self._build_single_rail("Inspector", "mdi.eye-outline")
        self._insp_rail.clicked.connect(lambda: self.set_inspector_visible(True))
        self._mon_rail  = self._build_single_rail("Monitor", "mdi.pulse")
        self._mon_rail.clicked.connect(lambda: self.set_monitor_visible(True))

        # Stacked rail — shown when both panels are collapsed
        self._stacked_rail = _StackedRail()
        self._stacked_rail.inspector_clicked.connect(lambda: self.set_inspector_visible(True))
        self._stacked_rail.monitor_clicked.connect(lambda: self.set_monitor_visible(True))

        # Collapse buttons — callers inject these into panel headers
        self.inspector_collapse_btn = self._build_collapse_btn()
        self.inspector_collapse_btn.clicked.connect(lambda: self.set_inspector_visible(False))
        self.monitor_collapse_btn = self._build_collapse_btn()
        self.monitor_collapse_btn.clicked.connect(lambda: self.set_monitor_visible(False))

        # Inner splitter for when both panels are visible
        self._inner = QSplitter(Qt.Horizontal)
        self._inner.setHandleWidth(1)
        self._inner.addWidget(inspector)
        self._inner.addWidget(monitor)
        self._inner.setCollapsible(0, False)
        self._inner.setCollapsible(1, False)
        self._inner.setSizes([320, 296])

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._insp_rail)
        lay.addWidget(self._inner, 1)
        lay.addWidget(self._mon_rail)
        lay.addWidget(self._stacked_rail)

        self._sync_layout()
        self.apply_theme()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_single_rail(self, label: str, icon_name: str) -> _ClickWidget:
        rail = _ClickWidget()
        rail.setFixedWidth(RAIL_W)
        rail.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        rail.setCursor(Qt.PointingHandCursor)
        rail._icon_name = icon_name

        lay = QVBoxLayout(rail)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)

        rail._chev = QLabel("›")
        rail._chev.setFixedHeight(28)
        rail._chev.setAlignment(Qt.AlignCenter)
        lay.addWidget(rail._chev)

        rail._icon_lbl = QLabel()
        rail._icon_lbl.setFixedHeight(26)
        rail._icon_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(rail._icon_lbl)

        rail._vert_lbl = VerticalLabel(label.upper())
        f = rail._vert_lbl.font()
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        rail._vert_lbl.setFont(f)
        lay.addWidget(rail._vert_lbl, 1)

        return rail

    def _build_collapse_btn(self) -> QPushButton:
        btn = QPushButton("‹")
        btn.setFixedSize(_BTN_SZ, _BTN_SZ)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Collapse panel")
        return btn

    # ── layout state ──────────────────────────────────────────────────────────

    def _sync_layout(self) -> None:
        both_vis = self._insp_vis and self._mon_vis
        both_off = not self._insp_vis and not self._mon_vis

        # Inner splitter content
        self._inspector.setVisible(self._insp_vis)
        self._monitor.setVisible(self._mon_vis)

        # Single rails
        self._insp_rail.setVisible(not self._insp_vis and self._mon_vis)
        self._mon_rail.setVisible(not self._mon_vis and self._insp_vis)

        # Stacked rail / inner splitter
        self._stacked_rail.setVisible(both_off)
        self._inner.setVisible(not both_off)

        # Collapse buttons visibility
        self.inspector_collapse_btn.setVisible(self._insp_vis)
        self.monitor_collapse_btn.setVisible(self._mon_vis)

        # Width constraints
        if both_off:
            self.setFixedWidth(RAIL_W)
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)

    # ── public API ────────────────────────────────────────────────────────────

    def is_inspector_visible(self) -> bool:
        return self._insp_vis

    def is_monitor_visible(self) -> bool:
        return self._mon_vis

    def set_inspector_visible(self, visible: bool) -> None:
        if self._insp_vis == visible:
            return
        self._insp_vis = visible
        # When only one panel is showing, put its content directly; the inner
        # splitter hides the other child via setVisible on the widget.
        self._sync_layout()
        self.inspector_toggled.emit(visible)

    def set_monitor_visible(self, visible: bool) -> None:
        if self._mon_vis == visible:
            return
        self._mon_vis = visible
        self._sync_layout()
        self.monitor_toggled.emit(visible)

    def inner_splitter_sizes(self) -> list[int]:
        return list(self._inner.sizes())

    def set_inner_splitter_sizes(self, sizes: list[int]) -> None:
        self._inner.setSizes(sizes)

    def apply_theme(self) -> None:
        _rail_ss = (
            f"_ClickWidget{{background:{PANEL_BG}; border:0;"
            f"border-left:1px solid {BORDER};}}"
            f"_ClickWidget[hover='true']{{background:{BG2};}}"
        )
        _chev_ss = (
            f"color:{SUBTEXT}; font-size:14px; font-weight:500; background:transparent;"
            f"border-bottom:1px solid {BORDER};"
        )
        _icon_ss = f"background:transparent; border-bottom:1px solid {BORDER};"
        _lbl_ss  = (
            f"color:{SUBTEXT}; font-size:10px; background:transparent;"
            f"font-family:'JetBrains Mono',monospace;"
        )
        _btn_ss  = (
            f"QPushButton{{background:transparent; border:none;"
            f"color:{SUBTEXT}; font-size:13px; font-weight:500; border-radius:4px;}}"
            f"QPushButton:hover{{background:{BG2}; color:{ACCENT};}}"
        )
        for rail in (self._insp_rail, self._mon_rail):
            rail.setStyleSheet(_rail_ss)
            rail._chev.setStyleSheet(_chev_ss)
            rail._icon_lbl.setStyleSheet(_icon_ss)
            rail._icon_lbl.setPixmap(
                _icons.pixmap(rail._icon_name, 14, color=str(SUBTEXT))
            )
            rail._vert_lbl.setStyleSheet(_lbl_ss)
        for btn in (self.inspector_collapse_btn, self.monitor_collapse_btn):
            btn.setStyleSheet(_btn_ss)
        self._stacked_rail.apply_theme()

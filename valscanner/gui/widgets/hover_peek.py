from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QApplication

from ..constants import PANEL_BG, BORDER, TEXT, SUBTEXT, ACCENT, CATEGORY_COLORS
from .. import icons as _icons
from ..theme import Spacing, Margins

CARD_W  = 240
THUMB_H = 120
HIDE_DELAY_MS = 100


class HoverPeekCard(QFrame):
    """Frameless floating card shown on table-row hover.

    Call show_for(row, global_cursor_pos, db_path) to display.
    Call hide_soon() to start the 100ms hide timer.
    """

    def __init__(self, parent=None):
        # Qt.ToolTip segfaults on Wayland (Fedora default) — use Qt.Tool instead
        if sys.platform == "linux":
            _flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus
        else:
            _flags = Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        super().__init__(parent, _flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(CARD_W)
        self.setStyleSheet(
            f"QFrame {{ background: {PANEL_BG}; border: 1px solid {BORDER};"
            f" border-radius: 8px; }}"
        )

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self.hide)

        self._db_path = ""
        self._build_ui()

    # ── public ────────────────────────────────────────────────────────────────

    def show_for(self, row: tuple, cursor_global: QPoint, db_path: str) -> None:
        """Populate and show the card near *cursor_global*."""
        self._hide_timer.stop()
        self._populate(row, db_path)
        self.adjustSize()
        self._position_near(cursor_global)
        self.show()
        self.raise_()

    def hide_soon(self) -> None:
        """Start the short hide delay (ignore if already hidden)."""
        if self.isVisible():
            self._hide_timer.start()

    def hide_now(self) -> None:
        self._hide_timer.stop()
        self.hide()

    # ── internal ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*Margins.NONE)
        lay.setSpacing(Spacing.NONE)

        # Thumbnail area
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(CARD_W, THUMB_H)
        self._thumb_lbl.setAlignment(Qt.AlignCenter)
        self._thumb_lbl.setStyleSheet(
            f"background: #1a1a1a; border: none;"
            f" border-top-left-radius: 8px; border-top-right-radius: 8px;"
        )
        lay.addWidget(self._thumb_lbl)

        # Metadata area
        meta = QFrame()
        meta.setStyleSheet("QFrame { background: transparent; border: none; }")
        ml = QVBoxLayout(meta)
        ml.setContentsMargins(Spacing.PX10, Spacing.SM, Spacing.PX10, Spacing.PX10)
        ml.setSpacing(Spacing.PX3)

        self._name_lbl = QLabel()
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 11px; font-weight: bold; background: transparent;"
        )
        ml.addWidget(self._name_lbl)

        self._cat_lbl = QLabel()
        self._cat_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: transparent;"
        )
        ml.addWidget(self._cat_lbl)

        self._size_lbl = QLabel()
        self._size_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: transparent;"
        )
        ml.addWidget(self._size_lbl)

        self._mod_lbl = QLabel()
        self._mod_lbl.setStyleSheet(
            f"color: {SUBTEXT}; font-size: 10px; background: transparent;"
        )
        ml.addWidget(self._mod_lbl)

        lay.addWidget(meta)

    def _populate(self, row: tuple, db_path: str) -> None:
        from ..models import _THUMB_CACHE, _FOLDER_SENTINEL
        path  = row[0] if len(row) > 0 else ""
        name  = row[1] if len(row) > 1 else ""
        cat   = row[2] if len(row) > 2 else "other"
        size  = row[4] if len(row) > 4 else ""
        mod   = row[5] if len(row) > 5 else ""

        if cat == _FOLDER_SENTINEL:
            cat = "folder"

        # Thumbnail
        px = _THUMB_CACHE.get(path, cat, size=CARD_W)
        if not px.isNull():
            scaled = px.scaled(
                CARD_W, THUMB_H,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Centre-crop to CARD_W × THUMB_H
            if scaled.width() > CARD_W or scaled.height() > THUMB_H:
                x = (scaled.width() - CARD_W) // 2
                y = (scaled.height() - THUMB_H) // 2
                scaled = scaled.copy(x, y, CARD_W, THUMB_H)
            self._thumb_lbl.setPixmap(scaled)
        else:
            fallback = _icons.pixmap(f"cat-{cat}", 48,
                                     color=CATEGORY_COLORS.get(cat, str(SUBTEXT)))
            self._thumb_lbl.setPixmap(fallback)

        # Text fields
        self._name_lbl.setText(name or Path(path).name or path)
        color = CATEGORY_COLORS.get(cat, str(SUBTEXT))
        self._cat_lbl.setText(cat)
        self._cat_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent;"
        )
        self._size_lbl.setText(size or "")
        self._size_lbl.setVisible(bool(size))
        self._mod_lbl.setText(mod[:16] if mod else "")
        self._mod_lbl.setVisible(bool(mod))

    def _position_near(self, cursor_global: QPoint) -> None:
        screen = QApplication.screenAt(cursor_global)
        if screen is None and QApplication.screens():
            screen = QApplication.screens()[0]

        x = cursor_global.x() + 20
        y = cursor_global.y() - self.height() // 2

        if screen:
            geo = screen.availableGeometry()
            if x + CARD_W > geo.right():
                x = cursor_global.x() - CARD_W - 8
            if y < geo.top():
                y = geo.top() + 4
            if y + self.height() > geo.bottom():
                y = geo.bottom() - self.height() - 4

        self.move(x, y)

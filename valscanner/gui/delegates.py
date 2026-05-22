from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT, BORDER, SEL_BG, SEL_TEXT
from .fonts import mono_font_family
from .density import get_row_height
from .models import _THUMB_CACHE
from . import icons as _icons


def _css_to_qcolor(css: str) -> QColor:
    """Convert CSS colour string (rgba() or #RRGGBBAA) to QColor."""
    if css.startswith("rgba("):
        parts = css[5:-1].split(",")
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = round(float(parts[3]) * 255)
        return QColor(r, g, b, a)
    c = QColor(css[:7])
    c.setAlpha(int(css[7:], 16) if len(css) == 9 else 0x55)
    return c

def _sel_bg() -> QColor:
    return _css_to_qcolor(str(SEL_BG))

def _sel_text() -> QColor:
    return QColor(str(SEL_TEXT))


def _draw_checker(painter, rect: QRect) -> None:
    """Fill *rect* with a 8px checkerboard placeholder (no thumbnail available)."""
    sq = 8
    c1 = QColor(30, 30, 30)
    c2 = QColor(46, 46, 46)
    painter.save()
    painter.setClipRect(rect)
    cols = rect.width()  // sq + 1
    rows = rect.height() // sq + 1
    for row in range(rows):
        for col in range(cols):
            c = c1 if (row + col) % 2 == 0 else c2
            painter.fillRect(rect.x() + col * sq, rect.y() + row * sq, sq, sq, c)
    painter.restore()


class FileCardDelegate(QStyledItemDelegate):
    """Grid card: thumbnail/icon area + filename + size."""
    W     = 168
    H     = 152
    THUMB = 100

    def sizeHint(self, option, index):
        return QSize(self.W, self.H)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        if not row:
            return
        path, filename, category, _, size_human = row[0], row[1], row[2], row[3], row[4]
        selected  = bool(option.state & QStyle.State_Selected)
        sel_bg    = _sel_bg()
        sel_text  = _sel_text()
        cat_color = CATEGORY_COLORS.get(category, "#808080")

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        r = option.rect.adjusted(4, 4, -4, -4)

        # Card background + amber selection border
        bg = sel_bg if selected else QColor(str(PANEL_BG))
        painter.setBrush(QBrush(bg))
        bw = 2 if selected else 1
        painter.setPen(QPen(QColor(str(ACCENT) if selected else str(BORDER)), bw))
        painter.drawRoundedRect(r, 8, 8)

        # Thumbnail strip (clipped to rect so it doesn't bleed past card edges)
        tb_rect = QRect(r.x() + 1, r.y() + 1, r.width() - 2, self.THUMB)
        px = _THUMB_CACHE.get(path, category, self.THUMB)
        if not px.isNull():
            scaled = px.scaled(tb_rect.width(), self.THUMB,
                               Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            ox = tb_rect.x() + (tb_rect.width() - scaled.width()) // 2
            oy = tb_rect.y() + (self.THUMB - scaled.height()) // 2
            painter.save()
            painter.setClipRect(tb_rect)
            painter.drawPixmap(ox, oy, scaled)
            painter.restore()
        else:
            _draw_checker(painter, tb_rect)
            icon_px = _icons.pixmap(f"cat-{category}", 32, color=cat_color)
            if not icon_px.isNull():
                ix = tb_rect.x() + (tb_rect.width() - icon_px.width()) // 2
                iy = tb_rect.y() + (self.THUMB - icon_px.height()) // 2
                painter.drawPixmap(ix, iy, icon_px)

        # Category corner dot — 8px circle, top-right of card
        painter.setBrush(QBrush(QColor(cat_color)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(r.right() - 14, r.top() + 6, 8, 8)

        # Thin separator between thumb and text
        painter.fillRect(QRect(r.x() + 1, r.y() + self.THUMB, r.width() - 2, 1),
                         QColor(str(BORDER)))

        # Filename
        ty = r.y() + self.THUMB + 7
        fn = QFont(); fn.setPixelSize(11)
        painter.setFont(fn)
        painter.setPen(sel_text if selected else QColor(str(TEXT)))
        nm = QRect(r.x() + 6, ty, r.width() - 12, 16)
        painter.drawText(nm, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(filename, Qt.ElideRight, nm.width()))

        # Size
        fn.setPixelSize(10); painter.setFont(fn)
        painter.setPen(sel_text if selected else QColor(str(SUBTEXT)))
        painter.drawText(QRect(r.x() + 6, ty + 18, r.width() - 12, 13),
                         Qt.AlignLeft | Qt.AlignVCenter, size_human)

        painter.restore()


class FileRowDelegate(QStyledItemDelegate):
    """Compact single-line row: color swatch + name + size + category chip."""

    @property
    def H(self) -> int:
        return get_row_height()

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.H)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        if not row:
            return
        path, filename, category, _, size_human = row[0], row[1], row[2], row[3], row[4]
        selected = bool(option.state & QStyle.State_Selected)
        sel_bg   = _sel_bg()
        sel_text = _sel_text()

        painter.save()
        r  = option.rect
        bg = sel_bg if selected else QColor(str(ROW_ALT) if index.row() % 2 else str(DARK_BG))
        painter.fillRect(r, bg)

        painter.setRenderHint(painter.RenderHint.Antialiasing)
        cat_color = CATEGORY_COLORS.get(category, "#808080")

        sw = QRect(r.x() + 8, r.y() + (r.height() - 10) // 2, 10, 10)
        painter.setBrush(QBrush(QColor(cat_color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(sw, 3, 3)

        fn = QFont(mono_font_family()); fn.setPixelSize(12)
        painter.setFont(fn)
        painter.setPen(sel_text if selected else QColor(str(TEXT)))
        avail = int(r.width() * 0.55)
        nm = QRect(r.x() + 26, r.y(), avail, r.height())
        painter.drawText(nm, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(filename, Qt.ElideRight, avail))

        painter.setPen(sel_text if selected else QColor(str(SUBTEXT)))
        fn.setPixelSize(11); painter.setFont(fn)
        sz = QRect(r.right() - 140, r.y(), 72, r.height())
        painter.drawText(sz, Qt.AlignRight | Qt.AlignVCenter, size_human)

        chip = QRect(r.right() - 62, r.y() + (r.height() - 16) // 2, 56, 16)
        cc   = QColor(cat_color)
        bg2  = QColor(cat_color); bg2.setAlpha(35)
        bdr  = QColor(cat_color); bdr.setAlpha(100)
        painter.setBrush(QBrush(bg2))
        painter.setPen(QPen(bdr, 1))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(cc)
        fn.setPixelSize(9); painter.setFont(fn)
        painter.drawText(chip, Qt.AlignCenter, category[:8])

        painter.restore()

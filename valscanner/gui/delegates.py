from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT, BORDER, SEL_BG, SEL_TEXT
from .models import _THUMB_CACHE


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

_SEL_BG   = _css_to_qcolor(SEL_BG)
_SEL_TEXT = QColor(SEL_TEXT)


class FileCardDelegate(QStyledItemDelegate):
    """Grid card: thumbnail/icon area + filename + size."""
    W     = 158
    H     = 142
    THUMB = 90

    def sizeHint(self, option, index):
        return QSize(self.W, self.H)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        if not row:
            return
        path, filename, category, _, size_human = row[0], row[1], row[2], row[3], row[4]
        selected = bool(option.state & QStyle.State_Selected)

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        r = option.rect.adjusted(4, 4, -4, -4)

        bg = _SEL_BG if selected else QColor(PANEL_BG)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(ACCENT if selected else BORDER), 1))
        painter.drawRoundedRect(r, 8, 8)

        cat_color = CATEGORY_COLORS.get(category, "#9E9E9E")
        tb_bg     = QColor(cat_color)
        tb_bg.setAlpha(28)
        tb_rect = QRect(r.x() + 1, r.y() + 1, r.width() - 2, self.THUMB)
        painter.fillRect(tb_rect, tb_bg)

        px = _THUMB_CACHE.get(path, category, self.THUMB - 8)
        if not px.isNull():
            scale = min((self.THUMB - 8) / max(px.height(), 1),
                        (r.width() - 8)  / max(px.width(),  1))
            dw = int(px.width()  * scale)
            dh = int(px.height() * scale)
            dx = r.x() + (r.width() - dw) // 2
            dy = r.y() + (self.THUMB - dh) // 2
            painter.drawPixmap(dx, dy,
                               px.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        painter.fillRect(QRect(r.x() + 1, r.y() + self.THUMB, r.width() - 2, 2),
                         QColor(cat_color))

        ty = r.y() + self.THUMB + 7
        fn = QFont(); fn.setPixelSize(11)
        painter.setFont(fn)
        painter.setPen(_SEL_TEXT if selected else QColor(TEXT))
        nm = QRect(r.x() + 6, ty, r.width() - 12, 16)
        painter.drawText(nm, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(filename, Qt.ElideRight, nm.width()))

        fn.setPixelSize(10); painter.setFont(fn)
        painter.setPen(_SEL_TEXT if selected else QColor(SUBTEXT))
        painter.drawText(QRect(r.x() + 6, ty + 18, r.width() - 12, 13),
                         Qt.AlignLeft | Qt.AlignVCenter, size_human)

        painter.restore()


class FileRowDelegate(QStyledItemDelegate):
    """Compact single-line row: color swatch + name + size + category chip."""
    H = 28

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.H)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        if not row:
            return
        path, filename, category, _, size_human = row[0], row[1], row[2], row[3], row[4]
        selected = bool(option.state & QStyle.State_Selected)

        painter.save()
        r  = option.rect
        bg = _SEL_BG if selected else QColor(ROW_ALT if index.row() % 2 else DARK_BG)
        painter.fillRect(r, bg)

        painter.setRenderHint(painter.RenderHint.Antialiasing)
        cat_color = CATEGORY_COLORS.get(category, "#9E9E9E")

        sw = QRect(r.x() + 8, r.y() + (r.height() - 10) // 2, 10, 10)
        painter.setBrush(QBrush(QColor(cat_color)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(sw, 3, 3)

        fn = QFont(); fn.setPixelSize(12)
        painter.setFont(fn)
        painter.setPen(_SEL_TEXT if selected else QColor(TEXT))
        avail = int(r.width() * 0.55)
        nm = QRect(r.x() + 26, r.y(), avail, r.height())
        painter.drawText(nm, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(filename, Qt.ElideRight, avail))

        painter.setPen(_SEL_TEXT if selected else QColor(SUBTEXT))
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

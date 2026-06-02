from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT, BORDER, SEL_BG, SEL_TEXT
from .fonts import mono_font_family
from .density import get_row_height
from .models import _THUMB_CACHE, _FOLDER_SENTINEL
from . import icons as _icons


# Module-level caches: paint() runs hundreds of times per scroll, so every
# QColor / QFont / QBrush we allocate inside the inner loop shows up in the
# flame chart. Cache by the source string (which is what the theme module
# already uses as the canonical representation) so a theme change just lands
# under a fresh key without invalidating anything.

_qcolor_cache: dict[str, QColor] = {}
_qbrush_cache: dict[str, QBrush] = {}
_qfont_cache: dict[tuple, QFont] = {}
_ALIGN_HC_VC = Qt.AlignHCenter | Qt.AlignVCenter
_ALIGN_L_VC = Qt.AlignLeft | Qt.AlignVCenter
_ALIGN_R_VC = Qt.AlignRight | Qt.AlignVCenter
_ELIDE_RIGHT = Qt.ElideRight


def _qc(css: str) -> QColor:
    c = _qcolor_cache.get(css)
    if c is not None:
        return c
    if css.startswith("rgba("):
        parts = css[5:-1].split(",")
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = round(float(parts[3]) * 255)
        c = QColor(r, g, b, a)
    elif len(css) == 9 and css.startswith("#"):
        c = QColor(css[:7])
        c.setAlpha(int(css[7:], 16))
    else:
        c = QColor(css)
    _qcolor_cache[css] = c
    return c


def _qb(css: str) -> QBrush:
    b = _qbrush_cache.get(css)
    if b is None:
        b = QBrush(_qc(css))
        _qbrush_cache[css] = b
    return b


def _qfont(family: str, pixel_size: int) -> QFont:
    key = (family, pixel_size)
    f = _qfont_cache.get(key)
    if f is None:
        f = QFont(family) if family else QFont()
        f.setPixelSize(pixel_size)
        _qfont_cache[key] = f
    return f


def _css_to_qcolor(css: str) -> QColor:
    """Convert CSS colour string (rgba() or #RRGGBBAA) to QColor.

    Retained for external callers; internally we route through the cached
    `_qc()` helper above, which subsumes this routine and memoizes it.
    """
    return _qc(css)


def _sel_bg() -> QColor:
    return _qc(str(SEL_BG))


def _sel_text() -> QColor:
    return _qc(str(SEL_TEXT))


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
        selected = bool(option.state & QStyle.State_Selected)
        sel_bg   = _qc(str(SEL_BG))
        sel_text = _qc(str(SEL_TEXT))
        cat_color_str = CATEGORY_COLORS.get(category, "#808080")
        cat_qc = _qc(cat_color_str)

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        r = option.rect.adjusted(4, 4, -4, -4)

        bg = sel_bg if selected else _qc(str(PANEL_BG))
        painter.setBrush(QBrush(bg))
        bw = 2 if selected else 1
        painter.setPen(QPen(_qc(str(ACCENT) if selected else str(BORDER)), bw))
        painter.drawRoundedRect(r, 8, 8)

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
            is_folder = (category == _FOLDER_SENTINEL)
            fill_color = QColor(_qc(str(ACCENT) if is_folder else cat_color_str))
            fill_color.setAlpha(40)
            painter.fillRect(tb_rect, fill_color)
            icon_name = "folder" if is_folder else f"cat-{category}"
            cat_icon = _icons.icon(icon_name, color=str(TEXT))
            if not cat_icon.isNull():
                _SZ = 32
                painter.save()
                painter.setClipRect(tb_rect)
                ix = tb_rect.x() + (tb_rect.width() - _SZ) // 2
                iy = tb_rect.y() + (self.THUMB - _SZ) // 2
                cat_icon.paint(painter, QRect(ix, iy, _SZ, _SZ))
                painter.restore()

        painter.setBrush(QBrush(cat_qc))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(r.right() - 14, r.top() + 6, 8, 8)

        painter.fillRect(QRect(r.x() + 1, r.y() + self.THUMB, r.width() - 2, 1),
                         _qc(str(BORDER)))

        ty = r.y() + self.THUMB + 7
        painter.setFont(_qfont("", 11))
        painter.setPen(sel_text if selected else _qc(str(TEXT)))
        nm = QRect(r.x() + 6, ty, r.width() - 12, 16)
        painter.drawText(nm, _ALIGN_HC_VC,
                         painter.fontMetrics().elidedText(filename, _ELIDE_RIGHT, nm.width()))

        painter.setFont(_qfont("", 10))
        painter.setPen(sel_text if selected else _qc(str(SUBTEXT)))
        painter.drawText(QRect(r.x() + 6, ty + 18, r.width() - 12, 13),
                         _ALIGN_HC_VC, size_human)

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
        sel_bg   = _qc(str(SEL_BG))
        sel_text = _qc(str(SEL_TEXT))

        painter.save()
        r = option.rect
        bg = sel_bg if selected else _qc(str(ROW_ALT) if index.row() & 1 else str(DARK_BG))
        painter.fillRect(r, bg)

        painter.setRenderHint(painter.RenderHint.Antialiasing)
        cat_color_str = CATEGORY_COLORS.get(category, "#808080")
        cat_qc = _qc(cat_color_str)

        sw = QRect(r.x() + 8, r.y() + (r.height() - 10) // 2, 10, 10)
        painter.setBrush(QBrush(cat_qc))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(sw, 3, 3)

        painter.setFont(_qfont(mono_font_family(), 12))
        painter.setPen(sel_text if selected else _qc(str(TEXT)))
        avail = int(r.width() * 0.55)
        nm = QRect(r.x() + 26, r.y(), avail, r.height())
        painter.drawText(nm, _ALIGN_L_VC,
                         painter.fontMetrics().elidedText(filename, _ELIDE_RIGHT, avail))

        painter.setPen(sel_text if selected else _qc(str(SUBTEXT)))
        painter.setFont(_qfont(mono_font_family(), 11))
        sz = QRect(r.right() - 140, r.y(), 72, r.height())
        painter.drawText(sz, _ALIGN_R_VC, size_human)

        chip = QRect(r.right() - 62, r.y() + (r.height() - 16) // 2, 56, 16)
        # Chip backing/border: derive once per category and cache.
        bg2_key = f"{cat_color_str}@35"
        bdr_key = f"{cat_color_str}@100"
        bg2 = _qcolor_cache.get(bg2_key)
        if bg2 is None:
            bg2 = QColor(cat_qc); bg2.setAlpha(35)
            _qcolor_cache[bg2_key] = bg2
        bdr = _qcolor_cache.get(bdr_key)
        if bdr is None:
            bdr = QColor(cat_qc); bdr.setAlpha(100)
            _qcolor_cache[bdr_key] = bdr
        painter.setBrush(QBrush(bg2))
        painter.setPen(QPen(bdr, 1))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(cat_qc)
        painter.setFont(_qfont(mono_font_family(), 9))
        painter.drawText(chip, Qt.AlignCenter, category[:8])

        painter.restore()

"""Vector icons for the GUI, backed by qtawesome + Material Design Icons.

Why this module exists
----------------------
All Qt-visible icons go through :func:`icon`. That gives us one place to:

* swap the icon font (qtawesome supports Font Awesome, Phosphor, Codicons, …)
* recolour every glyph when the theme changes
* fall back gracefully if qtawesome is somehow missing at runtime

Callers normally use the semantic name registry (``NAMES``) rather than raw
MDI glyph names, so renaming a glyph upstream only touches this file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap

from .constants import ACCENT, RED, SUBTEXT, TEXT, YELLOW

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

try:
    import qtawesome as _qta
    _HAS_QTA = True
except ImportError:  # pragma: no cover - guarded by pyproject dep
    _qta = None
    _HAS_QTA = False


# Semantic name → MDI glyph. Centralised so individual call sites stay readable
# and a future style swap only edits this map.
NAMES: dict[str, str] = {
    # generic file/folder
    "folder":         "mdi.folder",
    "folder-open":    "mdi.folder-open",
    "folder-search":  "mdi.folder-search",
    "file":           "mdi.file-document-outline",
    "file-multiple":  "mdi.file-multiple",

    # categories (mirror CATEGORY_COLORS keys in constants.py)
    "cat-photo":        "mdi.image",
    "cat-video":        "mdi.movie-open",
    "cat-audio":        "mdi.music",
    "cat-document":     "mdi.file-document",
    "cat-spreadsheet":  "mdi.file-chart",
    "cat-presentation": "mdi.file-presentation-box",
    "cat-code":         "mdi.code-tags",
    "cat-data":         "mdi.database",
    "cat-archive":      "mdi.archive",
    "cat-executable":   "mdi.cog-box",
    "cat-font":         "mdi.format-font",
    "cat-ebook":        "mdi.book-open-page-variant",
    "cat-image":        "mdi.image",
    "cat-other":        "mdi.file-question-outline",

    # actions / chrome
    "scan":          "mdi.radar",
    "search":        "mdi.magnify",
    "stop":          "mdi.stop-circle",
    "options":       "mdi.tune-variant",
    "filters":       "mdi.filter-variant",
    "browse":        "mdi.folder-search-outline",
    "open":          "mdi.folder-open-outline",
    "save":          "mdi.content-save-outline",
    "export-csv":    "mdi.file-delimited-outline",
    "export-json":   "mdi.code-json",
    "database":      "mdi.database",
    "database-edit": "mdi.database-edit",
    "console":       "mdi.console-line",
    "refresh":       "mdi.refresh",
    "delete":        "mdi.trash-can-outline",
    "close":         "mdi.close",
    "check":         "mdi.check",
    "warning":       "mdi.alert-outline",
    "success":       "mdi.check-circle-outline",
    "info":          "mdi.information-outline",
    "settings":      "mdi.cog-outline",
    "copy":          "mdi.content-copy",
    "clipboard":     "mdi.clipboard-text-outline",
    "rocket":        "mdi.rocket-launch-outline",
    "play":          "mdi.play-circle-outline",

    # view modes
    "view-grid":     "mdi.view-grid-outline",
    "view-list":     "mdi.view-list-outline",
    "view-table":    "mdi.table-large",

    # similar / analysis
    "similar":       "mdi.set-merge",
    "tag":           "mdi.tag-outline",
    "tag-multiple":  "mdi.tag-multiple-outline",
    "scale":         "mdi.scale-balance",
    "package":       "mdi.package-variant-closed",

    # status dots
    "dot":           "mdi.circle",
    "dot-small":     "mdi.circle-small",
}


def _resolve(name: str) -> str:
    """Map semantic name → qtawesome glyph identifier."""
    return NAMES.get(name, name if "." in name else f"mdi.{name}")


def icon(
    name: str,
    *,
    color: Optional[str] = None,
    color_disabled: Optional[str] = None,
    color_active: Optional[str] = None,
) -> QIcon:
    """Return a themed :class:`QIcon` for *name*.

    *name* is either a semantic key from :data:`NAMES` or a raw qtawesome glyph
    identifier (``"mdi.folder"``). *color* defaults to the theme TEXT color so
    icons match surrounding labels on every platform.
    """
    if not _HAS_QTA:
        return QIcon()
    glyph = _resolve(name)
    kwargs: dict[str, object] = {"color": color or str(TEXT)}
    if color_disabled:
        kwargs["color_disabled"] = color_disabled
    else:
        kwargs["color_disabled"] = str(SUBTEXT)
    if color_active:
        kwargs["color_active"] = color_active
    try:
        return _qta.icon(glyph, **kwargs)
    except Exception:
        return QIcon()


def pixmap(name: str, size: int, *, color: Optional[str] = None) -> QPixmap:
    """Render *name* as a :class:`QPixmap` at *size* px (square)."""
    ic = icon(name, color=color)
    if ic.isNull():
        return QPixmap()
    return ic.pixmap(QSize(size, size))


def app_logo_pixmap(size: int, *, radius: Optional[int] = None,
                    asset_name: str = "icon.png") -> QPixmap:
    """Load the app logo and clip it to a rounded square.

    *radius* defaults to ``size // 5`` (matches the 7-8 px corner radius used in the
    rest of the UI at typical icon sizes). Pass ``radius=size // 2`` for a full
    circle. Returns an empty pixmap if the asset is missing.
    """
    src_path = _ASSETS_DIR / asset_name
    src = QPixmap(str(src_path))
    if src.isNull():
        return QPixmap()
    if radius is None:
        radius = max(4, size // 5)
    scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), float(radius), float(radius))
    painter.setClipPath(clip)
    offset_x = (scaled.width() - size) // 2
    offset_y = (scaled.height() - size) // 2
    painter.drawPixmap(-offset_x, -offset_y, scaled)
    painter.end()
    return out


# Convenience colour-bound helpers used in a handful of places ----------------

def accent_icon(name: str) -> QIcon:
    return icon(name, color=str(ACCENT))


def danger_icon(name: str) -> QIcon:
    return icon(name, color=str(RED))


def warn_icon(name: str) -> QIcon:
    return icon(name, color=str(YELLOW))


def subtle_icon(name: str) -> QIcon:
    return icon(name, color=str(SUBTEXT))

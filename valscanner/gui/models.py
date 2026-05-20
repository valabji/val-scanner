from __future__ import annotations

from sqlalchemy import text

from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, QAbstractListModel, QRect
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QBrush

from ..core.db import repo_for
from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, SUBTEXT
from . import icons as _icons

COLUMNS = ["Filename", "Category", "Size", "Modified", "Tags", "Path"]
COL_IDX = {c: i for i, c in enumerate(COLUMNS)}

_GROUP_SENTINEL = "__group__"
_FOLDER_SENTINEL = "__folder__"


def make_folder_row(path: str, file_count: int, total_bytes: int, human_size: str = "") -> tuple:
    """Create a folder row tuple compatible with FileTableModel.

    Layout mirrors file rows: (path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta)
    For folders: category is _FOLDER_SENTINEL, tags is "<N> files".
    """
    from pathlib import Path as _Path
    name = _Path(path).name or path
    tag = f"{file_count:,} files" if file_count else "empty"
    return (path, name, _FOLDER_SENTINEL, total_bytes or 0, human_size, "", tag, "")


class FileTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._rows: list[tuple] = []

    def load(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def append_rows(self, new_rows: list) -> None:
        """Append rows without resetting the model (preserves scroll position)."""
        if not new_rows:
            return
        first = len(self._rows)
        last = first + len(new_rows) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._rows.extend(new_rows)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        row = self._rows[index.row()]
        if row[2] == _GROUP_SENTINEL:
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if row[2] == _GROUP_SENTINEL:
            if role == Qt.DisplayRole:
                return row[1] if col == 0 else ""
            if role == Qt.BackgroundRole:
                return QColor(PANEL_BG)
            if role == Qt.ForegroundRole:
                return QColor(ACCENT)
            if role == Qt.FontRole:
                f = QFont(); f.setBold(True); f.setPixelSize(11); return f
            if role == Qt.TextAlignmentRole:
                return Qt.AlignLeft | Qt.AlignVCenter
            return None

        if row[2] == _FOLDER_SENTINEL:
            mapping = {
                COL_IDX["Filename"]: row[1],
                COL_IDX["Category"]: "folder",
                COL_IDX["Size"]:     row[4],
                COL_IDX["Modified"]: "",
                COL_IDX["Tags"]:     row[6],
                COL_IDX["Path"]:     row[0],
            }
            if role == Qt.DisplayRole:
                return mapping.get(col, "")
            if role == Qt.DecorationRole and col == COL_IDX["Filename"]:
                return _icons.icon("folder", color=str(ACCENT))
            if role == Qt.ForegroundRole:
                if col == COL_IDX["Category"]:
                    return QColor(ACCENT)
                if col in (COL_IDX["Path"], COL_IDX["Tags"]):
                    return QColor(SUBTEXT)
                return QColor("#dcdcfa")
            if role == Qt.FontRole and col == COL_IDX["Filename"]:
                f = QFont(); f.setBold(True); return f
            if role == Qt.BackgroundRole:
                return QColor(ROW_ALT if index.row() % 2 else DARK_BG)
            if role == Qt.UserRole:
                return row
            if role == Qt.TextAlignmentRole and col == COL_IDX["Size"]:
                return Qt.AlignRight | Qt.AlignVCenter
            return None

        mapping = {
            COL_IDX["Filename"]: row[1],
            COL_IDX["Category"]: row[2],
            COL_IDX["Size"]:     row[4],
            COL_IDX["Modified"]: row[5],
            COL_IDX["Tags"]:     row[6],
            COL_IDX["Path"]:     row[0],
        }
        if role == Qt.DisplayRole:
            return mapping.get(col, "")
        if role == Qt.DecorationRole and col == COL_IDX["Filename"]:
            cat = row[2]
            return _icons.icon(f"cat-{cat}", color=CATEGORY_COLORS.get(cat, str(SUBTEXT)))
        if role == Qt.ForegroundRole:
            if col == COL_IDX["Category"]:
                return QColor(CATEGORY_COLORS.get(row[2], "#9E9E9E"))
            if col in (COL_IDX["Path"], COL_IDX["Tags"]):
                return QColor(SUBTEXT)
        if role == Qt.BackgroundRole:
            return QColor(ROW_ALT if index.row() % 2 else DARK_BG)
        if role == Qt.UserRole:
            return row
        if role == Qt.TextAlignmentRole and col == COL_IDX["Size"]:
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        self.beginResetModel()
        reverse = (order == Qt.DescendingOrder)
        if column == COL_IDX["Size"]:
            inner_key = lambda r: r[3]
        else:
            key_map = {
                COL_IDX["Filename"]: lambda r: r[1].lower(),
                COL_IDX["Category"]: lambda r: r[2].lower(),
                COL_IDX["Modified"]: lambda r: r[5],
                COL_IDX["Tags"]:     lambda r: r[6],
                COL_IDX["Path"]:     lambda r: r[0].lower(),
            }
            inner_key = key_map.get(column, lambda r: r[1].lower())

        # Folders always come first regardless of sort direction
        def composite_key(r):
            is_folder = (len(r) > 2 and r[2] == _FOLDER_SENTINEL)
            # Negate the folder flag so folders (True -> 0) precede files (False -> 1)
            return (0 if is_folder else 1, inner_key(r))

        self._rows.sort(key=composite_key, reverse=False)
        if reverse:
            # Sort folders first then files separately, with files reversed
            folders = [r for r in self._rows if len(r) > 2 and r[2] == _FOLDER_SENTINEL]
            files = [r for r in self._rows if not (len(r) > 2 and r[2] == _FOLDER_SENTINEL)]
            folders.sort(key=inner_key, reverse=True)
            files.sort(key=inner_key, reverse=True)
            self._rows = folders + files
        self.endResetModel()


def _make_cat_pixmap(category: str, size: int) -> QPixmap:
    color = QColor(CATEGORY_COLORS.get(category, "#9E9E9E"))
    dim   = max(size, 8)
    px    = QPixmap(dim, dim)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(color))
    p.setPen(Qt.NoPen)
    r = max(2, dim // 5)
    p.drawRoundedRect(0, 0, dim, dim, r, r)
    glyph_size = max(12, int(dim * 0.55))
    glyph = _icons.pixmap(f"cat-{category}", glyph_size, color="#ffffff")
    if not glyph.isNull():
        gx = (dim - glyph.width()) // 2
        gy = (dim - glyph.height()) // 2
        p.drawPixmap(gx, gy, glyph)
    else:
        p.setPen(QColor("white"))
        f = QFont()
        f.setPixelSize(max(9, dim // 2))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRect(0, 0, dim, dim), Qt.AlignCenter, (category or "?")[0].upper())
    p.end()
    return px


class ThumbnailCache:
    def __init__(self):
        self._px:     dict[str, QPixmap] = {}
        self._cat_px: dict[str, QPixmap] = {}
        self._db_path = ""

    def set_db(self, path: str) -> None:
        self._db_path = path
        self._px.clear()

    def get(self, path: str, category: str, size: int = 96) -> QPixmap:
        key = f"{path}@{size}"
        if key in self._px:
            return self._px[key]
        if self._db_path and category in ("photo", "image", "video"):
            try:
                engine = repo_for(self._db_path).engine
                with engine.connect() as conn:
                    row = conn.execute(
                        text("SELECT t.data FROM thumbnails t"
                             " JOIN files f ON f.id = t.file_id WHERE f.path=:p"),
                        {"p": path},
                    ).fetchone()
                if row:
                    px = QPixmap()
                    px.loadFromData(row[0])
                    px = px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._px[key] = px
                    return px
            except Exception:
                pass
        cat_key = f"{category}@{size}"
        if cat_key not in self._cat_px:
            self._cat_px[cat_key] = _make_cat_pixmap(category, size)
        px = self._cat_px[cat_key]
        self._px[key] = px
        return px


_THUMB_CACHE = ThumbnailCache()


class FileIconModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple] = []

    def load(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        is_folder = (row[2] == _FOLDER_SENTINEL)
        if role == Qt.DisplayRole:
            return row[1]
        if role == Qt.DecorationRole:
            if is_folder:
                return _icons.icon("folder", color=str(ACCENT))
            cat = row[2]
            return _icons.icon(f"cat-{cat}", color=CATEGORY_COLORS.get(cat, str(SUBTEXT)))
        if role == Qt.UserRole:
            return row
        if role == Qt.ToolTipRole:
            if is_folder:
                return f"{row[1]}\n{row[4]}  ·  {row[6]}\n{row[0]}"
            return f"{row[1]}\n{row[4]}  ·  {row[2]}\n{row[0]}"
        return None

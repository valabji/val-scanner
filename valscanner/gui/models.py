from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, QAbstractListModel, QObject, Signal
from PySide6.QtGui import QColor, QFont, QPixmap, QImage

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT
from . import icons as _icons

COLUMNS = ["Filename", "Category", "Size", "Modified", "Hash", "Tags", "Path"]
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
    return (path, name, _FOLDER_SENTINEL, total_bytes or 0, human_size, "", tag, "", "")


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
                COL_IDX["Hash"]:     "",
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
                if col in (COL_IDX["Path"], COL_IDX["Tags"], COL_IDX["Hash"]):
                    return QColor(SUBTEXT)
                return QColor(str(TEXT))
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
            COL_IDX["Hash"]:     row[7] if len(row) > 7 else "",
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
                return QColor(CATEGORY_COLORS.get(row[2], str(SUBTEXT)))
            if col in (COL_IDX["Path"], COL_IDX["Tags"], COL_IDX["Hash"]):
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
                COL_IDX["Hash"]:     lambda r: (r[7] if len(r) > 7 else "") or "",
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


class _ThumbBridge(QObject):
    """GUI-thread QObject that receives QImage results from the worker and
    forwards them as ready QPixmaps. Created lazily after QApplication exists.
    """
    ready = Signal(str, QPixmap, int)  # path, pixmap, size

    def __init__(self) -> None:
        super().__init__()

    def on_worker_ready(self, path: str, img: QImage, size: int) -> None:
        # Runs on the GUI thread (queued connection from worker).
        if img is None or img.isNull():
            # Emit empty pixmap so callers can stop polling.
            self.ready.emit(path, QPixmap(), size)
            return
        px = QPixmap.fromImage(img)
        if not px.isNull():
            px = px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.ready.emit(path, px, size)


class ThumbnailCache:
    """Async thumbnail cache.

    ``get()`` returns immediately:
      - the cached pixmap (or empty if known-absent),
      - or an empty QPixmap while a request is queued.

    Listeners connect ``bridge.ready`` to be notified when a pixmap arrives.
    The cache owns a single ``ThumbnailLoadWorker`` (started lazily after
    QApplication exists) and a ``_ThumbBridge`` for cross-thread delivery.

    Cache values: a QPixmap (possibly null) means resolved; absence means
    "not yet requested"; presence in ``_inflight`` means "queued, waiting."
    """

    _PX_MAX = 1024

    def __init__(self):
        # LRU. Values: QPixmap (resolved — possibly null/empty). Missing key = not requested.
        self._px: OrderedDict[str, QPixmap] = OrderedDict()
        self._inflight: set[str] = set()

    def _put(self, key: str, px: QPixmap) -> None:
        self._px[key] = px
        self._px.move_to_end(key)
        while len(self._px) > self._PX_MAX:
            self._px.popitem(last=False)
        self._db_path = ""
        self._bridge: _ThumbBridge | None = None
        self._worker = None  # ThumbnailLoadWorker (lazy)

    @property
    def bridge(self) -> _ThumbBridge:
        """Lazy GUI-thread signal hub. Safe to call only after QApplication."""
        if self._bridge is None:
            self._bridge = _ThumbBridge()
            self._bridge.ready.connect(self._on_ready)
        return self._bridge

    def _ensure_worker(self) -> None:
        if self._worker is not None or not self._db_path:
            return
        # Imported lazily to avoid circular import (workers -> models).
        from .workers import ThumbnailLoadWorker
        # Touch the bridge first so we have a GUI-thread receiver before the
        # worker can emit; connect with queued delivery (auto).
        b = self.bridge
        self._worker = ThumbnailLoadWorker(self._db_path)
        self._worker.thumb_ready.connect(b.on_worker_ready)
        self._worker.start()

    def set_db(self, path: str) -> None:
        self._db_path = path
        self._px.clear()
        self._inflight.clear()
        if self._worker is not None:
            self._worker.set_db(path)
        else:
            self._ensure_worker()

    def get(self, path: str, category: str, size: int = 96) -> QPixmap:
        """Return cached pixmap immediately; queue a fetch if not yet known.

        Always non-blocking; never touches the database from the calling thread.
        """
        key = f"{path}@{size}"
        if key in self._px:
            self._px.move_to_end(key)
            return self._px[key]
        if not self._db_path or category not in ("photo", "image", "video"):
            # Mark as resolved-empty so we don't try again.
            self._put(key, QPixmap())
            return self._px[key]
        if key in self._inflight:
            return QPixmap()
        self._ensure_worker()
        if self._worker is None:
            self._put(key, QPixmap())
            return self._px[key]
        self._inflight.add(key)
        self._worker.enqueue(path, size)
        return QPixmap()

    def _on_ready(self, path: str, px: QPixmap, size: int) -> None:
        """Slot on the GUI thread — store result and forward to subscribers."""
        key = f"{path}@{size}"
        self._inflight.discard(key)
        self._put(key, px)

    def shutdown(self) -> None:
        """Stop the background worker — call from MainWindow.closeEvent."""
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
            self._worker = None


_THUMB_CACHE = ThumbnailCache()


class FileIconModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple] = []
        self._path_to_rows: dict[str, list[int]] = {}
        # Subscribe to async thumbnail arrivals so the grid view repaints.
        try:
            _THUMB_CACHE.bridge.ready.connect(self._on_thumb_ready)
        except Exception:
            pass

    def load(self, rows):
        self.beginResetModel()
        self._rows = list(rows)
        self._path_to_rows = {}
        for i, r in enumerate(self._rows):
            if r and r[0]:
                self._path_to_rows.setdefault(r[0], []).append(i)
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

    def _on_thumb_ready(self, path: str, _px: QPixmap, _size: int) -> None:
        # Re-emit dataChanged for any row showing this path so the delegate repaints.
        rows = self._path_to_rows.get(path)
        if not rows:
            return
        for ri in rows:
            idx = self.index(ri, 0)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])

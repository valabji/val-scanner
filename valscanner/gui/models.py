from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import (
    Qt, QModelIndex, QAbstractTableModel, QAbstractListModel,
    QObject, Signal, QMimeData, QUrl,
)
from PySide6.QtGui import QColor, QFont, QPixmap, QImage

from .constants import CATEGORY_COLORS, DARK_BG, PANEL_BG, ROW_ALT, ACCENT, TEXT, SUBTEXT
from . import icons as _icons

COLUMNS = ["Filename", "Category", "Size", "Modified", "Hash", "Tags", "Path"]
COL_IDX = {c: i for i, c in enumerate(COLUMNS)}

_GROUP_SENTINEL = "__group__"
_FOLDER_SENTINEL = "__folder__"

# Column indices hoisted to module level so the data() hot path skips dict
# lookups for COL_IDX["Filename"] etc.
_COL_FILENAME = COL_IDX["Filename"]
_COL_CATEGORY = COL_IDX["Category"]
_COL_SIZE = COL_IDX["Size"]
_COL_MODIFIED = COL_IDX["Modified"]
_COL_HASH = COL_IDX["Hash"]
_COL_TAGS = COL_IDX["Tags"]
_COL_PATH = COL_IDX["Path"]
# Cells whose foreground is the subtext color (path, tags, hash).
_SUBTEXT_COLS = frozenset((_COL_PATH, _COL_TAGS, _COL_HASH))

# Module-scoped QColor / QFont caches — constructing a QColor or QFont per
# data() call adds up fast in large tables.
_qcolor_cache: dict[str, "QColor"] = {}


def _qc(key: str) -> "QColor":
    c = _qcolor_cache.get(key)
    if c is None:
        c = QColor(key)
        _qcolor_cache[key] = c
    return c


def _cat_color(cat: str) -> "QColor":
    """Cached QColor for a category, falling back to subtext."""
    key = f"cat:{cat}"
    c = _qcolor_cache.get(key)
    if c is None:
        c = QColor(CATEGORY_COLORS.get(cat, str(SUBTEXT)))
        _qcolor_cache[key] = c
    return c


# Fonts and alignments — built once.
def _make_bold_font(px: int | None = None) -> "QFont":
    f = QFont()
    f.setBold(True)
    if px is not None:
        f.setPixelSize(px)
    return f


_GROUP_FONT: "QFont | None" = None
_FOLDER_BOLD_FONT: "QFont | None" = None


def _group_font() -> "QFont":
    global _GROUP_FONT
    if _GROUP_FONT is None:
        _GROUP_FONT = _make_bold_font(11)
    return _GROUP_FONT


def _folder_bold_font() -> "QFont":
    global _FOLDER_BOLD_FONT
    if _FOLDER_BOLD_FONT is None:
        _FOLDER_BOLD_FONT = _make_bold_font()
    return _FOLDER_BOLD_FONT


_ALIGN_RIGHT_VC = Qt.AlignRight | Qt.AlignVCenter
_ALIGN_LEFT_VC = Qt.AlignLeft | Qt.AlignVCenter


def make_folder_row(path: str, file_count: int, total_bytes: int, human_size: str = "") -> tuple:
    """Create a folder row tuple compatible with FileTableModel.

    Layout mirrors file rows: (path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta)
    For folders: category is _FOLDER_SENTINEL, tags is "<N> files".
    """
    from pathlib import Path as _Path
    name = _Path(path).name or path
    tag = f"{file_count:,} files" if file_count else "empty"
    return (path, name, _FOLDER_SENTINEL, total_bytes or 0, human_size, "", tag, "", "")


def _rows_to_mime(rows: list, indexes) -> QMimeData:
    """Build a text/uri-list + plain-text drag payload from selected rows.

    Skips group-header rows and de-duplicates by row index, so a multi-cell
    selection of one row yields a single path.
    """
    md = QMimeData()
    paths: list[str] = []
    seen: set[int] = set()
    for idx in indexes:
        r = idx.row()
        if r in seen or not (0 <= r < len(rows)):
            continue
        seen.add(r)
        row = rows[r]
        if len(row) > 2 and row[2] == _GROUP_SENTINEL:
            continue
        if row and row[0]:
            paths.append(row[0])
    if paths:
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        md.setText("\n".join(paths))
    return md


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
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list", "text/plain"]

    def mimeData(self, indexes) -> QMimeData:
        return _rows_to_mime(self._rows, indexes)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r_idx = index.row()
        rows = self._rows
        if r_idx < 0 or r_idx >= len(rows):
            return None
        row = rows[r_idx]
        col = index.column()
        sentinel = row[2]

        if sentinel == _GROUP_SENTINEL:
            if role == Qt.DisplayRole:
                return row[1] if col == 0 else ""
            if role == Qt.BackgroundRole:
                return _qc(str(PANEL_BG))
            if role == Qt.ForegroundRole:
                return _qc(str(ACCENT))
            if role == Qt.FontRole:
                return _group_font()
            if role == Qt.TextAlignmentRole:
                return _ALIGN_LEFT_VC
            return None

        if sentinel == _FOLDER_SENTINEL:
            if role == Qt.DisplayRole:
                if col == _COL_FILENAME:
                    return row[1]
                if col == _COL_CATEGORY:
                    return "folder"
                if col == _COL_SIZE:
                    return row[4]
                if col == _COL_TAGS:
                    return row[6]
                if col == _COL_PATH:
                    return row[0]
                return ""
            if role == Qt.DecorationRole and col == _COL_FILENAME:
                return _icons.icon("folder", color=str(ACCENT))
            if role == Qt.ForegroundRole:
                if col == _COL_CATEGORY:
                    return _qc(str(ACCENT))
                if col in _SUBTEXT_COLS:
                    return _qc(str(SUBTEXT))
                return _qc(str(TEXT))
            if role == Qt.FontRole and col == _COL_FILENAME:
                return _folder_bold_font()
            if role == Qt.BackgroundRole:
                return _qc(str(ROW_ALT) if (r_idx & 1) else str(DARK_BG))
            if role == Qt.UserRole:
                return row
            if role == Qt.TextAlignmentRole and col == _COL_SIZE:
                return _ALIGN_RIGHT_VC
            return None

        # File row.
        if role == Qt.DisplayRole:
            if col == _COL_FILENAME:
                return row[1]
            if col == _COL_CATEGORY:
                return row[2]
            if col == _COL_SIZE:
                return row[4]
            if col == _COL_MODIFIED:
                return row[5]
            if col == _COL_HASH:
                return row[7] if len(row) > 7 else ""
            if col == _COL_TAGS:
                return row[6]
            if col == _COL_PATH:
                return row[0]
            return ""
        if role == Qt.DecorationRole and col == _COL_FILENAME:
            cat = row[2]
            return _icons.icon(f"cat-{cat}", color=CATEGORY_COLORS.get(cat, str(SUBTEXT)))
        if role == Qt.ForegroundRole:
            if col == _COL_CATEGORY:
                return _cat_color(row[2])
            if col in _SUBTEXT_COLS:
                return _qc(str(SUBTEXT))
        if role == Qt.BackgroundRole:
            return _qc(str(ROW_ALT) if (r_idx & 1) else str(DARK_BG))
        if role == Qt.UserRole:
            return row
        if role == Qt.TextAlignmentRole and col == _COL_SIZE:
            return _ALIGN_RIGHT_VC
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        self.beginResetModel()
        reverse = (order == Qt.DescendingOrder)
        if column == _COL_SIZE:
            inner_key = lambda r: r[3]
        elif column == _COL_FILENAME:
            inner_key = lambda r: r[1].lower()
        elif column == _COL_CATEGORY:
            inner_key = lambda r: r[2].lower()
        elif column == _COL_MODIFIED:
            inner_key = lambda r: r[5]
        elif column == _COL_HASH:
            inner_key = lambda r: (r[7] if len(r) > 7 else "") or ""
        elif column == _COL_TAGS:
            inner_key = lambda r: r[6]
        elif column == _COL_PATH:
            inner_key = lambda r: r[0].lower()
        else:
            inner_key = lambda r: r[1].lower()

        # Single partition pass instead of two list comprehensions on reverse.
        folders: list = []
        files: list = []
        for r in self._rows:
            if len(r) > 2 and r[2] == _FOLDER_SENTINEL:
                folders.append(r)
            else:
                files.append(r)
        folders.sort(key=inner_key, reverse=reverse)
        files.sort(key=inner_key, reverse=reverse)
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
        self._db_path = ""
        self._bridge: _ThumbBridge | None = None
        self._worker = None  # ThumbnailLoadWorker (lazy)

    def _put(self, key: str, px: QPixmap) -> None:
        self._px[key] = px
        self._px.move_to_end(key)
        while len(self._px) > self._PX_MAX:
            self._px.popitem(last=False)

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
        """Stop the background worker — call from MainWindow.closeEvent.

        Waits for the worker to exit so the QThread does not outlive the
        QApplication (which would SIGABRT at interpreter shutdown).
        """
        w = self._worker
        if w is not None:
            try:
                w.stop()
            except Exception:
                pass
            try:
                w.quit()
            except Exception:
                pass
            try:
                if w.isRunning() and not w.wait(1500):
                    w.terminate()
                    w.wait(1500)
            except RuntimeError:
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

    def append_rows(self, new_rows: list) -> None:
        """Append rows without resetting the model (preserves scroll position)."""
        if not new_rows:
            return
        first = len(self._rows)
        last = first + len(new_rows) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        for offset, r in enumerate(new_rows):
            if r and r[0]:
                self._path_to_rows.setdefault(r[0], []).append(first + offset)
        self._rows.extend(new_rows)
        self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        row = self._rows[index.row()]
        if len(row) > 2 and row[2] == _GROUP_SENTINEL:
            return Qt.ItemIsEnabled
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list", "text/plain"]

    def mimeData(self, indexes) -> QMimeData:
        return _rows_to_mime(self._rows, indexes)

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

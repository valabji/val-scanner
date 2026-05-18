from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.scanner import scan
from ..core.similarity import find_similar_folders

PAGE_SIZE = 2_000


class ScanWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(dict)
    error    = Signal(str)

    def __init__(self, root: str, db_path: str, compute_hash: bool,
                 label: str = "", options: dict | None = None):
        super().__init__()
        self.root         = Path(root)
        self.db_path      = db_path
        self.compute_hash = compute_hash
        self.label        = label
        self.options      = options or {}
        self._stop        = False
        self._cancel_event = threading.Event()
        self._pid         = ""  # assigned by caller after registration

    def run(self) -> None:
        try:
            original_walk = os.walk
            counter       = [0]
            worker_self   = self

            def instrumented_walk(root, *args, **kwargs):
                for dirpath, dirnames, filenames in original_walk(root, *args, **kwargs):
                    if worker_self._stop:
                        return
                    for fname in filenames:
                        counter[0] += 1
                        if counter[0] % 50 == 0:
                            worker_self.progress.emit(
                                counter[0],
                                str(Path(dirpath) / fname),
                            )
                            if worker_self._pid:
                                from .panels.process import ProcessRegistry
                                reg = ProcessRegistry.instance()
                                reg.heartbeat(worker_self._pid)
                                reg.push_log(
                                    worker_self._pid,
                                    f"Indexed {counter[0]:,} files — {Path(dirpath).name}",
                                )
                    yield dirpath, dirnames, filenames

            os.walk = instrumented_walk
            stats   = scan(self.root, self.db_path, self.compute_hash,
                           label=self.label, cancel_event=self._cancel_event, **self.options)
            os.walk = original_walk
            self.finished.emit(stats)
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_done(self._pid)
        except Exception as e:
            os.walk = original_walk  # type: ignore[assignment]
            self.finished.emit({"scanned": 0, "errors": 1, "skipped": 0})
            self.error.emit(str(e))
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_error(self._pid, str(e))

    def stop(self) -> None:
        self._stop = True
        self._cancel_event.set()


class AnalysisWorker(QThread):
    finished = Signal(list)
    error    = Signal(str)

    def __init__(self, db_path: str, min_files: int, threshold: float,
                 scan_ids: list | None = None):
        super().__init__()
        self.db_path   = db_path
        self.min_files = min_files
        self.threshold = threshold
        self.scan_ids  = scan_ids
        self._stop     = False
        self._pid      = ""

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().heartbeat(self._pid)

            if self._stop:
                if self._pid:
                    from .panels.process import ProcessRegistry
                    ProcessRegistry.instance().mark_done(self._pid)
                self.finished.emit([])
                return

            results = find_similar_folders(
                self.db_path,
                min_files=self.min_files,
                threshold=self.threshold,
                scan_ids=self.scan_ids,
                stop_flag=lambda: self._stop,
            )
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_done(self._pid)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_error(self._pid, str(e))


class DbLoadWorker(QThread):
    """Background worker for initial database load."""
    db_loaded = Signal(dict)  # Emits {"total": N, "total_size": M, "rows": [...]}
    error     = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, page_size: int = PAGE_SIZE):
        super().__init__()
        self.db_path   = db_path
        self.scan_id   = scan_id
        self.page_size = page_size

    def run(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            sid = self.scan_id
            where = "WHERE scan_id=?" if sid else ""
            args = (sid,) if sid else ()

            # Get counts and total size
            total, = conn.execute(f"SELECT COUNT(*) FROM files {where}", args).fetchone()
            total_size, = conn.execute(f"SELECT SUM(size_bytes) FROM files {where}", args).fetchone()

            # Load first page
            page_args = (sid, self.page_size, 0) if sid else (self.page_size, 0)
            rows = conn.execute(
                f"SELECT path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta "
                f"FROM files {where} ORDER BY filename LIMIT ? OFFSET ?",
                page_args,
            ).fetchall()
            conn.close()

            self.db_loaded.emit({
                "total": total,
                "total_size": total_size or 0,
                "rows": list(rows),
            })
        except Exception as e:
            self.error.emit(str(e))


class LazyLoadWorker(QThread):
    """Background worker for paginated file loading from database."""
    rows_ready = Signal(list)
    error      = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, offset: int,
                 page_size: int = PAGE_SIZE):
        super().__init__()
        self.db_path   = db_path
        self.scan_id   = scan_id
        self.offset    = offset
        self.page_size = page_size

    def run(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            where = "WHERE scan_id=?" if self.scan_id else ""
            args = (self.scan_id, self.page_size, self.offset) if self.scan_id else (self.page_size, self.offset)
            rows = conn.execute(
                f"SELECT path, filename, category, size_bytes, size_human, modified_at, tags, extra_meta "
                f"FROM files {where} ORDER BY filename LIMIT ? OFFSET ?",
                args,
            ).fetchall()
            conn.close()
            self.rows_ready.emit(list(rows))
        except Exception as e:
            self.error.emit(str(e))


class BrowserLoadWorker(QThread):
    """Loads folders + files at a specific path level (immediate children only)."""
    contents_ready = Signal(dict)  # {"folders": [...], "files": [...], "path": str, "scan_id": int}
    error          = Signal(str)

    def __init__(self, db_path: str, scan_id: int | None, path: str):
        super().__init__()
        self.db_path = db_path
        self.scan_id = scan_id
        self.path    = path  # "" for root view, otherwise absolute folder path

    def run(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            sid  = self.scan_id

            if not self.path:
                # Root view: show scan roots as top-level folders
                if sid:
                    rows = conn.execute(
                        "SELECT id, root, label, file_count, total_bytes FROM scans WHERE id=?",
                        (sid,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, root, label, file_count, total_bytes FROM scans"
                    ).fetchall()
                folders = [
                    (r[1], r[3] or 0, r[4] or 0, r[0])  # (path, file_count, total_bytes, scan_id)
                    for r in rows
                ]
                files = []
            else:
                # Subfolders at this path (immediate children only)
                like_prefix = self.path.rstrip("/") + "/%"
                like_deeper = self.path.rstrip("/") + "/%/%"

                if sid:
                    folder_rows = conn.execute(
                        "SELECT path, file_count, total_bytes, scan_id FROM folders "
                        "WHERE scan_id=? AND path LIKE ? AND path NOT LIKE ? "
                        "ORDER BY path",
                        (sid, like_prefix, like_deeper),
                    ).fetchall()
                else:
                    folder_rows = conn.execute(
                        "SELECT path, file_count, total_bytes, scan_id FROM folders "
                        "WHERE path LIKE ? AND path NOT LIKE ? ORDER BY path",
                        (like_prefix, like_deeper),
                    ).fetchall()
                folders = list(folder_rows)

                # Files at this path (not in subfolders)
                if sid:
                    file_rows = conn.execute(
                        "SELECT path, filename, category, size_bytes, size_human, "
                        "modified_at, tags, extra_meta "
                        "FROM files WHERE scan_id=? AND path LIKE ? AND path NOT LIKE ? "
                        "ORDER BY filename",
                        (sid, like_prefix, like_deeper),
                    ).fetchall()
                else:
                    file_rows = conn.execute(
                        "SELECT path, filename, category, size_bytes, size_human, "
                        "modified_at, tags, extra_meta "
                        "FROM files WHERE path LIKE ? AND path NOT LIKE ? "
                        "ORDER BY filename",
                        (like_prefix, like_deeper),
                    ).fetchall()
                files = list(file_rows)

            conn.close()

            self.contents_ready.emit({
                "folders":  folders,
                "files":    files,
                "path":     self.path,
                "scan_id":  sid or 0,
            })
        except Exception as e:
            self.error.emit(str(e))

from __future__ import annotations
import os
import sqlite3
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
                           label=self.label, **self.options)
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
                return

            results = find_similar_folders(
                self.db_path,
                min_files=self.min_files,
                threshold=self.threshold,
                scan_ids=self.scan_ids,
                stop_flag=lambda: self._stop,
            )
            if not self._stop:
                self.finished.emit(results)
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_done(self._pid)
        except Exception as e:
            self.error.emit(str(e))
            if self._pid:
                from .panels.process import ProcessRegistry
                ProcessRegistry.instance().mark_error(self._pid, str(e))


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

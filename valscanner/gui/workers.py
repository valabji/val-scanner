from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.scanner import scan
from ..core.similarity import find_similar_folders


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
                    yield dirpath, dirnames, filenames

            os.walk = instrumented_walk
            stats   = scan(self.root, self.db_path, self.compute_hash,
                           label=self.label, **self.options)
            os.walk = original_walk
            self.finished.emit(stats)
        except Exception as e:
            os.walk = original_walk  # type: ignore[assignment]
            self.finished.emit({"scanned": 0, "errors": 1, "skipped": 0})
            self.error.emit(str(e))

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

    def run(self) -> None:
        try:
            results = find_similar_folders(
                self.db_path,
                min_files=self.min_files,
                threshold=self.threshold,
                scan_ids=self.scan_ids,
            )
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

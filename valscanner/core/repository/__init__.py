from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select

from ..schema import files as _files_t, folders as _folders_t, scans as _scans_t
from .analysis import AnalysisMixin
from .cache import CacheMixin
from .files import FilesMixin
from .folders import FoldersMixin
from .media import MediaMixin
from .scans import ScansMixin
from .search import SearchMixin


class Repository(
    ScansMixin, FilesMixin, FoldersMixin,
    MediaMixin, SearchMixin, AnalysisMixin, CacheMixin,
):
    """Single entry point for all database reads and writes.

    Construct with either an engine or a URL string. Construction is cheap
    after the first call for a given URL because the engine cache lives in
    `db_config.get_engine`, and `create_all` runs at most once per engine.
    """

    def summary(self) -> dict:
        with self._engine.connect() as conn:
            total_files = conn.execute(select(func.count()).select_from(_files_t)).scalar() or 0
            total_bytes = conn.execute(select(func.sum(_files_t.c.size_bytes))).scalar() or 0
            scan_rows = conn.execute(
                select(
                    _scans_t.c.id, _scans_t.c.label, _scans_t.c.root,
                    _scans_t.c.scanned_at, _scans_t.c.file_count, _scans_t.c.total_human,
                ).order_by(_scans_t.c.id)
            ).fetchall()
            by_category = conn.execute(
                select(_files_t.c.category, func.count(), func.sum(_files_t.c.size_bytes))
                .group_by(_files_t.c.category)
                .order_by(func.count().desc())
            ).fetchall()
            top_ext = conn.execute(
                select(_files_t.c.extension, func.count())
                .group_by(_files_t.c.extension)
                .order_by(func.count().desc())
                .limit(10)
            ).fetchall()
            raw_tags = conn.execute(
                select(_files_t.c.tags).where(_files_t.c.tags != "")
            ).fetchall()
            top_folders = conn.execute(
                select(_folders_t.c.path,
                       func.sum(_folders_t.c.total_bytes),
                       func.sum(_folders_t.c.file_count))
                .group_by(_folders_t.c.path)
                .order_by(func.sum(_folders_t.c.total_bytes).desc())
                .limit(10)
            ).fetchall()

        tag_counter: Counter = Counter()
        for (tag_str,) in raw_tags:
            for t in (tag_str or "").split(", "):
                tag_counter[t.strip()] += 1

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "scans": [dict(r._mapping) for r in scan_rows],
            "by_category": [{"category": r[0], "count": r[1], "bytes": r[2]} for r in by_category],
            "top_extensions": [{"extension": r[0], "count": r[1]} for r in top_ext],
            "top_tags": tag_counter.most_common(10),
            "top_folders": [{"path": r[0], "bytes": r[1], "file_count": r[2]} for r in top_folders],
        }


__all__ = ["Repository"]

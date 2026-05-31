from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select, text

from ..schema import (
    files as _files_t,
    folders as _folders_t,
    scans as _scans_t,
    thumbnails as _thumbs_t,
    media_samples as _media_t,
    gui_cache as _cache_t,
    analysis_runs as _runs_t,
)
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

    def db_status(self) -> dict:
        dialect = self.dialect
        files_id   = _files_t.c.id
        thumbs_fid = _thumbs_t.c.file_id
        media_fid  = _media_t.c.file_id

        with self._engine.connect() as conn:
            if dialect == "sqlite":
                page_count = conn.execute(text("PRAGMA page_count")).scalar() or 0
                page_size  = conn.execute(text("PRAGMA page_size")).scalar() or 4096
                db_bytes   = page_count * page_size
            else:
                db_bytes = conn.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar() or 0

            row_counts = {}
            for name, tbl in [
                ("scans",         _scans_t),
                ("files",         _files_t),
                ("folders",       _folders_t),
                ("thumbnails",    _thumbs_t),
                ("media_samples", _media_t),
                ("gui_cache",     _cache_t),
                ("analysis_runs", _runs_t),
            ]:
                row_counts[name] = conn.execute(
                    select(func.count()).select_from(tbl)
                ).scalar() or 0

            scan_breakdown = conn.execute(
                select(
                    _scans_t.c.id,
                    _scans_t.c.label,
                    _scans_t.c.root,
                    func.count(_files_t.c.id).label("file_count"),
                    func.coalesce(func.sum(_files_t.c.size_bytes), 0).label("indexed_bytes"),
                )
                .select_from(
                    _scans_t.outerjoin(_files_t, _files_t.c.scan_id == _scans_t.c.id)
                )
                .group_by(_scans_t.c.id, _scans_t.c.label, _scans_t.c.root)
                .order_by(_scans_t.c.id)
            ).fetchall()

            # NOT EXISTS short-circuits on first match — avoids full hash of large tables
            orphan_files = conn.execute(
                select(func.count()).select_from(_files_t).where(
                    ~select(func.count()).select_from(_scans_t)
                     .where(_scans_t.c.id == _files_t.c.scan_id)
                     .correlate(_files_t).scalar_subquery().bool_op(">")(0)
                )
            ).scalar() or 0
            orphan_folders = conn.execute(
                select(func.count()).select_from(_folders_t).where(
                    ~select(func.count()).select_from(_scans_t)
                     .where(_scans_t.c.id == _folders_t.c.scan_id)
                     .correlate(_folders_t).scalar_subquery().bool_op(">")(0)
                )
            ).scalar() or 0
            orphan_thumbs = conn.execute(
                select(func.count()).select_from(_thumbs_t).where(
                    ~select(func.count()).select_from(_files_t)
                     .where(files_id == thumbs_fid)
                     .correlate(_thumbs_t).scalar_subquery().bool_op(">")(0)
                )
            ).scalar() or 0
            orphan_media = conn.execute(
                select(func.count()).select_from(_media_t).where(
                    ~select(func.count()).select_from(_files_t)
                     .where(files_id == media_fid)
                     .correlate(_media_t).scalar_subquery().bool_op(">")(0)
                )
            ).scalar() or 0

        total_indexed = sum(r.indexed_bytes for r in scan_breakdown)
        scans_out = []
        for r in scan_breakdown:
            pct = (r.indexed_bytes / total_indexed * 100) if total_indexed else 0
            scans_out.append({
                "id":            r.id,
                "label":         r.label,
                "root":          r.root,
                "file_count":    r.file_count,
                "indexed_bytes": r.indexed_bytes,
                "pct":           pct,
            })

        return {
            "dialect":       dialect,
            "db_url":        str(self._engine.url),
            "db_bytes":      db_bytes,
            "row_counts":    row_counts,
            "total_indexed": total_indexed,
            "scans":         scans_out,
            "orphans": {
                "files":         orphan_files,
                "folders":       orphan_folders,
                "thumbnails":    orphan_thumbs,
                "media_samples": orphan_media,
            },
        }


__all__ = ["Repository"]

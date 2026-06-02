from __future__ import annotations

from typing import Iterator

from sqlalchemy import and_, case, func, insert, or_, outerjoin, select, text, update
from sqlalchemy.exc import IntegrityError

from ..exceptions import DuplicateRecordError
from ..schema import files, media_samples, scans, thumbnails
from .base import RepositoryBase


_META_ELIGIBLE_CATEGORIES = ("photo", "audio")
_THUMB_ELIGIBLE_CATEGORIES = ("photo", "image", "video")
_SAMPLE_ELIGIBLE_CATEGORIES = ("audio", "video")


class FilesMixin(RepositoryBase):
    def insert_file(self, row: dict) -> int:
        try:
            with self._engine.begin() as conn:
                result = conn.execute(insert(files).values(**row))
            return result.inserted_primary_key[0]
        except IntegrityError as exc:
            raise DuplicateRecordError(str(exc)) from exc

    def insert_files_many(self, rows: list[dict]) -> int:
        # Bulk-insert with conflict-tolerance. Returns the number of rows that
        # actually landed (rowcount where reliable). Each insert is wrapped in
        # one transaction, so a batch of N replaces N per-row commits with one.
        if not rows:
            return 0
        if self.dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
            stmt = _sqlite_insert(files).prefix_with("OR IGNORE")
        elif self.dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as _pg_insert
            stmt = _pg_insert(files).on_conflict_do_nothing(
                index_elements=["scan_id", "path"]
            )
        else:
            stmt = insert(files)
        with self._engine.begin() as conn:
            result = conn.execute(stmt, rows)
        rc = result.rowcount
        return rc if isinstance(rc, int) and rc >= 0 else len(rows)

    def file_exists(self, scan_id: int, file_path: str) -> bool:
        """Check if a file already exists in a scan by path."""
        stmt = select(files.c.id).where(
            (files.c.scan_id == scan_id) & (files.c.path == file_path)
        ).limit(1)
        with self._engine.connect() as conn:
            return conn.execute(stmt).fetchone() is not None

    def existing_paths(self, scan_id: int) -> set[str]:
        """Bulk-load every indexed path for a scan into a set.

        Used by the resume path of enumerate_only() to replace O(N) per-file
        `file_exists` round-trips with a single query + O(1) hash lookups.
        """
        stmt = select(files.c.path).where(files.c.scan_id == scan_id)
        with self._engine.connect() as conn:
            return {row[0] for row in conn.execute(stmt)}

    def get_file(self, file_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(files).where(files.c.id == file_id)).fetchone()
        return dict(row._mapping) if row else None

    def get_file_with_scan_root(self, file_id: int) -> tuple[str, str] | None:
        stmt = (
            select(files.c.path, scans.c.root)
            .select_from(files.join(scans, files.c.scan_id == scans.c.id))
            .where(files.c.id == file_id)
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        return (row[0], row[1]) if row else None

    def list_files(self, scan_id: int | None = None, category: str | None = None,
                   page: int = 1, page_size: int = 200) -> list[dict]:
        stmt = select(files)
        if scan_id is not None:
            stmt = stmt.where(files.c.scan_id == scan_id)
        if category:
            stmt = stmt.where(files.c.category == category)
        stmt = stmt.order_by(files.c.id).offset((page - 1) * page_size).limit(page_size)
        with self._engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(stmt)]

    def iter_files_for_export(self, scan_id: int | None = None,
                              batch: int = 1000) -> Iterator[dict]:
        # Stream results so a multi-million-row export doesn't materialize the
        # entire table in memory before yielding the first dict.
        stmt = select(files).order_by(files.c.path)
        if scan_id is not None:
            stmt = stmt.where(files.c.scan_id == scan_id)
        with self._engine.connect().execution_options(stream_results=True) as conn:
            for row in conn.execute(stmt).yield_per(batch):
                yield dict(row._mapping)

    # ------------------------------------------------------------------ #
    # Per-phase enrichment queries                                        #
    # ------------------------------------------------------------------ #
    #
    # Each `iter_files_missing_*` yields dicts of (id, path, category,
    # extension, size_bytes) for files that still need a given phase.
    # Eligibility filters (category, extension) match the per-phase work
    # done in `valscanner.core.scanner`.  Streaming via `yield_per` keeps
    # memory bounded on very large scans.

    def _phase_columns(self):
        return (
            files.c.id, files.c.path, files.c.category,
            files.c.extension, files.c.size_bytes,
        )

    def iter_files_missing_metadata(self, scan_id: int,
                                    batch: int = 1000) -> Iterator[dict]:
        stmt = (
            select(*self._phase_columns())
            .where(files.c.scan_id == scan_id)
            .where(
                or_(
                    files.c.category.in_(_META_ELIGIBLE_CATEGORIES),
                    files.c.extension == ".pdf",
                )
            )
            .where(or_(files.c.extra_meta.is_(None), files.c.extra_meta == ""))
            .order_by(files.c.id)
        )
        with self._engine.connect().execution_options(stream_results=True) as conn:
            for row in conn.execute(stmt).yield_per(batch):
                yield dict(row._mapping)

    def iter_files_missing_hash(self, scan_id: int,
                                batch: int = 1000) -> Iterator[dict]:
        stmt = (
            select(*self._phase_columns())
            .where(files.c.scan_id == scan_id)
            .where(or_(files.c.sha256.is_(None), files.c.sha256 == ""))
            .order_by(files.c.id)
        )
        with self._engine.connect().execution_options(stream_results=True) as conn:
            for row in conn.execute(stmt).yield_per(batch):
                yield dict(row._mapping)

    def iter_files_missing_thumbnail(self, scan_id: int,
                                     batch: int = 1000) -> Iterator[dict]:
        join_ = outerjoin(files, thumbnails, files.c.id == thumbnails.c.file_id)
        stmt = (
            select(*self._phase_columns())
            .select_from(join_)
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_THUMB_ELIGIBLE_CATEGORIES))
            .where(thumbnails.c.file_id.is_(None))
            .order_by(files.c.id)
        )
        with self._engine.connect().execution_options(stream_results=True) as conn:
            for row in conn.execute(stmt).yield_per(batch):
                yield dict(row._mapping)

    def iter_files_missing_sample(self, scan_id: int,
                                  batch: int = 1000) -> Iterator[dict]:
        join_ = outerjoin(files, media_samples, files.c.id == media_samples.c.file_id)
        stmt = (
            select(*self._phase_columns())
            .select_from(join_)
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_SAMPLE_ELIGIBLE_CATEGORIES))
            .where(media_samples.c.file_id.is_(None))
            .order_by(files.c.id)
        )
        with self._engine.connect().execution_options(stream_results=True) as conn:
            for row in conn.execute(stmt).yield_per(batch):
                yield dict(row._mapping)

    def update_file_extra_meta(self, file_id: int, extra_meta_json: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(files)
                .where(files.c.id == file_id)
                .values(extra_meta=extra_meta_json)
            )

    def update_file_hash(self, file_id: int, sha256: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(files)
                .where(files.c.id == file_id)
                .values(sha256=sha256)
            )

    # ------------------------------------------------------------------ #
    # Per-phase status (used by --scan-status / future GUI)               #
    # ------------------------------------------------------------------ #

    def phase_status(self, scan_id: int) -> dict:
        """Return per-phase eligible/done counts for *scan_id*."""

        def _scalar(stmt) -> int:
            with self._engine.connect() as conn:
                return int(conn.execute(stmt).scalar() or 0)

        from sqlalchemy import func

        total = _scalar(
            select(func.count()).select_from(files).where(files.c.scan_id == scan_id)
        )

        meta_eligible = _scalar(
            select(func.count()).select_from(files)
            .where(files.c.scan_id == scan_id)
            .where(or_(
                files.c.category.in_(_META_ELIGIBLE_CATEGORIES),
                files.c.extension == ".pdf",
            ))
        )
        meta_done = _scalar(
            select(func.count()).select_from(files)
            .where(files.c.scan_id == scan_id)
            .where(or_(
                files.c.category.in_(_META_ELIGIBLE_CATEGORIES),
                files.c.extension == ".pdf",
            ))
            .where(and_(files.c.extra_meta.isnot(None), files.c.extra_meta != ""))
        )

        hash_done = _scalar(
            select(func.count()).select_from(files)
            .where(files.c.scan_id == scan_id)
            .where(and_(files.c.sha256.isnot(None), files.c.sha256 != ""))
        )

        thumb_eligible = _scalar(
            select(func.count()).select_from(files)
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_THUMB_ELIGIBLE_CATEGORIES))
        )
        thumb_done = _scalar(
            select(func.count())
            .select_from(files.join(thumbnails, files.c.id == thumbnails.c.file_id))
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_THUMB_ELIGIBLE_CATEGORIES))
        )

        sample_eligible = _scalar(
            select(func.count()).select_from(files)
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_SAMPLE_ELIGIBLE_CATEGORIES))
        )
        sample_done = _scalar(
            select(func.count())
            .select_from(files.join(media_samples, files.c.id == media_samples.c.file_id))
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_SAMPLE_ELIGIBLE_CATEGORIES))
        )

        return {
            "enumerate": {"eligible": total, "done": total},
            "metadata":  {"eligible": meta_eligible,  "done": meta_done},
            "thumbnails":{"eligible": thumb_eligible, "done": thumb_done},
            "hash":      {"eligible": total,          "done": hash_done},
            "samples":   {"eligible": sample_eligible,"done": sample_done},
        }

    def phase_status_by_extension(self, scan_id: int) -> dict[str, list[dict]]:
        """Return per-phase, per-extension eligible/done counts for *scan_id*.

        Each value is a list of ``{"ext", "eligible", "done"}`` dicts, sorted
        by ``(missing desc, eligible desc)`` so the largest gaps surface first.
        Eligibility filters match :meth:`phase_status`.
        """

        def _norm(ext: str | None) -> str:
            return ext if ext else "(no ext)"

        def _rows(stmt) -> list[dict]:
            with self._engine.connect() as conn:
                out = [
                    {
                        "ext": _norm(r[0]),
                        "eligible": int(r[1] or 0),
                        "done": int(r[2] or 0),
                    }
                    for r in conn.execute(stmt)
                ]
            out.sort(key=lambda x: (-(x["eligible"] - x["done"]), -x["eligible"]))
            return out

        # enumerate: every kept file is "done" by definition
        enum_stmt = (
            select(
                files.c.extension,
                func.count().label("eligible"),
                func.count().label("done"),
            )
            .where(files.c.scan_id == scan_id)
            .group_by(files.c.extension)
        )

        has_meta = case(
            (and_(files.c.extra_meta.isnot(None), files.c.extra_meta != ""), 1),
            else_=0,
        )
        meta_stmt = (
            select(
                files.c.extension,
                func.count().label("eligible"),
                func.sum(has_meta).label("done"),
            )
            .where(files.c.scan_id == scan_id)
            .where(or_(
                files.c.category.in_(_META_ELIGIBLE_CATEGORIES),
                files.c.extension == ".pdf",
            ))
            .group_by(files.c.extension)
        )

        has_hash = case(
            (and_(files.c.sha256.isnot(None), files.c.sha256 != ""), 1),
            else_=0,
        )
        hash_stmt = (
            select(
                files.c.extension,
                func.count().label("eligible"),
                func.sum(has_hash).label("done"),
            )
            .where(files.c.scan_id == scan_id)
            .group_by(files.c.extension)
        )

        thumb_stmt = (
            select(
                files.c.extension,
                func.count().label("eligible"),
                func.sum(case((thumbnails.c.file_id.isnot(None), 1), else_=0)).label("done"),
            )
            .select_from(outerjoin(files, thumbnails, files.c.id == thumbnails.c.file_id))
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_THUMB_ELIGIBLE_CATEGORIES))
            .group_by(files.c.extension)
        )

        sample_stmt = (
            select(
                files.c.extension,
                func.count().label("eligible"),
                func.sum(case((media_samples.c.file_id.isnot(None), 1), else_=0)).label("done"),
            )
            .select_from(outerjoin(files, media_samples, files.c.id == media_samples.c.file_id))
            .where(files.c.scan_id == scan_id)
            .where(files.c.category.in_(_SAMPLE_ELIGIBLE_CATEGORIES))
            .group_by(files.c.extension)
        )

        return {
            "enumerate":  _rows(enum_stmt),
            "metadata":   _rows(meta_stmt),
            "thumbnails": _rows(thumb_stmt),
            "hash":       _rows(hash_stmt),
            "samples":    _rows(sample_stmt),
        }

    def iter_similarity_rows(self, scan_ids: list[int] | None = None) -> Iterator[dict]:
        sql = (
            "SELECT f.scan_id, COALESCE(NULLIF(s.label,''), s.root) AS scan_label, "
            "       f.path, f.filename, f.extension, f.size_bytes, f.sha256, "
            "       LOWER(REPLACE(REPLACE(f.filename,' ',''),'_','')) AS norm_name "
            "FROM files f JOIN scans s ON s.id = f.scan_id"
        )
        params: dict = {}
        if scan_ids:
            placeholders = ",".join(f":sid{i}" for i in range(len(scan_ids)))
            sql += f" WHERE f.scan_id IN ({placeholders})"
            params = {f"sid{i}": sid for i, sid in enumerate(scan_ids)}
        with self._engine.connect() as conn:
            for row in conn.execute(text(sql), params):
                yield dict(row._mapping)

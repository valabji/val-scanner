from __future__ import annotations

from typing import Iterator

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from ..exceptions import DuplicateRecordError
from ..schema import files, scans
from .base import RepositoryBase


class FilesMixin(RepositoryBase):
    def insert_file(self, row: dict) -> int:
        try:
            with self._engine.begin() as conn:
                result = conn.execute(insert(files).values(**row))
            return result.inserted_primary_key[0]
        except IntegrityError as exc:
            raise DuplicateRecordError(str(exc)) from exc

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

    def iter_files_for_export(self, scan_id: int | None = None) -> Iterator[dict]:
        stmt = select(files).order_by(files.c.path)
        if scan_id is not None:
            stmt = stmt.where(files.c.scan_id == scan_id)
        with self._engine.connect() as conn:
            for row in conn.execute(stmt):
                yield dict(row._mapping)

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

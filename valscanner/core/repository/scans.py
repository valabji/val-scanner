from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, insert, select, update

from ..schema import scans
from .base import RepositoryBase


class ScansMixin(RepositoryBase):
    def list_scans(self) -> list[dict]:
        from sqlalchemy.exc import OperationalError
        stmt = select(
            scans.c.id, scans.c.label, scans.c.root, scans.c.scanned_at,
            scans.c.file_count, scans.c.total_bytes, scans.c.total_human,
        ).order_by(scans.c.id)
        with self._engine.connect() as conn:
            try:
                return [dict(r._mapping) for r in conn.execute(stmt)]
            except OperationalError:
                return []

    def get_scan(self, scan_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(scans).where(scans.c.id == scan_id)).fetchone()
        return dict(row._mapping) if row else None

    def create_scan(self, root: str, label: str = "",
                    scanned_at: str | None = None) -> int:
        now = scanned_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(scans).values(label=label, root=root, scanned_at=now)
            )
        return result.inserted_primary_key[0]

    def update_scan_totals(self, scan_id: int, file_count: int,
                           total_bytes: int, total_human: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(scans).where(scans.c.id == scan_id).values(
                    file_count=file_count,
                    total_bytes=total_bytes,
                    total_human=total_human,
                )
            )

    def update_scan_label(self, scan_id: int, label: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(scans).where(scans.c.id == scan_id).values(label=label))

    def delete_scan(self, scan_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(scans).where(scans.c.id == scan_id))

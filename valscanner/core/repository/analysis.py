from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import OperationalError

from ..schema import analysis_runs
from .base import RepositoryBase


class AnalysisMixin(RepositoryBase):
    def save_analysis_run(self, min_files: int, threshold: float,
                          scope_scan_ids: list[int] | None,
                          scope_label: str, duration_ms: int,
                          results: list, filters: dict | None = None) -> int:
        merged_filters = dict(filters or {})
        if scope_scan_ids is not None:
            merged_filters["scope_scan_ids"] = list(scope_scan_ids)
        with self._engine.begin() as conn:
            result = conn.execute(
                insert(analysis_runs).values(
                    ran_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    min_files=min_files,
                    threshold=threshold,
                    scope_label=scope_label,
                    duration_ms=duration_ms,
                    pair_count=len(results),
                    filters_json=json.dumps(merged_filters),
                    results_json=json.dumps(results),
                )
            )
        return result.inserted_primary_key[0]

    def list_analysis_runs(self) -> list[dict]:
        stmt = select(
            analysis_runs.c.id, analysis_runs.c.ran_at,
            analysis_runs.c.min_files, analysis_runs.c.threshold,
            analysis_runs.c.scope_label, analysis_runs.c.duration_ms,
            analysis_runs.c.pair_count, analysis_runs.c.filters_json,
        ).order_by(analysis_runs.c.id.desc())
        with self._engine.connect() as conn:
            try:
                rows = conn.execute(stmt).fetchall()
            except OperationalError:
                return []
        out: list[dict] = []
        for r in rows:
            d = dict(r._mapping)
            try:
                filters = json.loads(d.pop("filters_json") or "{}")
            except (json.JSONDecodeError, KeyError):
                filters = {}
            d["filters"] = filters
            d["scope_scan_ids"] = filters.get("scope_scan_ids", [])
            out.append(d)
        return out

    def load_analysis_run(self, run_id: int) -> dict | None:
        stmt = select(analysis_runs).where(analysis_runs.c.id == run_id)
        with self._engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        out = dict(row._mapping)
        try:
            out["results"] = json.loads(out.pop("results_json") or "[]")
        except json.JSONDecodeError:
            out["results"] = []
        try:
            filters = json.loads(out.pop("filters_json") or "{}")
        except (json.JSONDecodeError, KeyError):
            filters = {}
        out["filters"] = filters
        out["scope_scan_ids"] = filters.get("scope_scan_ids", [])
        return out

    def delete_analysis_run(self, run_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(analysis_runs).where(analysis_runs.c.id == run_id))

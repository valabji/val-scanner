from __future__ import annotations

import weakref

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .base import RepositoryBase


# Cache the FTS-availability probe per Engine. The probe used to open a fresh
# connection on every search call just to ask SQLite whether files_fts exists.
# FTS availability cannot change at runtime once the schema is built, so one
# probe per engine is enough.
_FTS_PROBE_CACHE: "weakref.WeakKeyDictionary[object, bool]" = weakref.WeakKeyDictionary()


class SearchMixin(RepositoryBase):
    # ── paged search used by /api/files and the GUI files panel ─────────────

    def search_paged(self, scan_id: int, search: str | None = None,
                     category: str | None = None,
                     page: int = 1, page_size: int = 100) -> dict:
        """Returns {total, page, page_size, items}.

        Each item dict contains: id, path, filename, size_bytes, size_human,
        category, tags, has_thumbnail.
        """
        if self.dialect == "sqlite":
            return self._search_paged_sqlite(scan_id, search, category, page, page_size)
        return self._search_paged_pg(scan_id, search, category, page, page_size)

    def _search_paged_sqlite(self, scan_id, search, category, page, page_size) -> dict:
        params: dict = {"sid": scan_id, "lim": page_size, "off": (page - 1) * page_size}
        from_clause = "FROM files f"
        order_clause = "ORDER BY f.path"
        where = ["f.scan_id = :sid"]
        if category:
            where.append("f.category = :cat")
            params["cat"] = category

        use_fts = False
        if search:
            cached = _FTS_PROBE_CACHE.get(self._engine)
            if cached is None:
                try:
                    with self._engine.connect() as conn:
                        conn.execute(text("SELECT 1 FROM files_fts LIMIT 1"))
                    cached = True
                except OperationalError:
                    cached = False
                _FTS_PROBE_CACHE[self._engine] = cached
            use_fts = cached

        if search and use_fts:
            from_clause = (
                "FROM files f JOIN files_fts fts ON fts.rowid = f.id"
            )
            where.append("files_fts MATCH :t")
            # SQLite FTS5 exposes a magic `rank` column for relevance.
            order_clause = "ORDER BY fts.rank"
            params["t"] = search
        elif search:
            # FTS absent → LIKE fallback (path + filename + tags).
            where.append("(f.path LIKE :like OR f.filename LIKE :like OR f.tags LIKE :like)")
            params["like"] = f"%{search}%"

        where_sql = " AND ".join(where)
        select_sql = (
            f"SELECT f.id, f.path, f.filename, f.size_bytes, f.size_human, "
            f"       f.category, f.tags, "
            f"       (SELECT 1 FROM thumbnails t WHERE t.file_id = f.id) AS has_thumb "
            f"{from_clause} WHERE {where_sql} {order_clause} LIMIT :lim OFFSET :off"
        )
        count_sql = f"SELECT COUNT(*) {from_clause} WHERE {where_sql}"

        count_params = {k: params[k] for k in params if k not in ("lim", "off")}
        with self._engine.connect() as conn:
            total = conn.execute(text(count_sql), count_params).scalar() or 0
            rows = conn.execute(text(select_sql), params).fetchall()

        return self._format_paged(rows, total, page, page_size)

    def _search_paged_pg(self, scan_id, search, category, page, page_size) -> dict:
        params: dict = {"sid": scan_id, "lim": page_size, "off": (page - 1) * page_size}
        where = ["f.scan_id = :sid"]
        order_clause = "ORDER BY f.path"
        if category:
            where.append("f.category = :cat")
            params["cat"] = category
        if search:
            where.append("f.fts @@ plainto_tsquery('english', :t)")
            order_clause = "ORDER BY ts_rank(f.fts, plainto_tsquery('english', :t)) DESC"
            params["t"] = search
        where_sql = " AND ".join(where)

        select_sql = (
            f"SELECT f.id, f.path, f.filename, f.size_bytes, f.size_human, "
            f"       f.category, f.tags, "
            f"       (SELECT 1 FROM thumbnails t WHERE t.file_id = f.id) AS has_thumb "
            f"FROM files f WHERE {where_sql} {order_clause} LIMIT :lim OFFSET :off"
        )
        count_sql = f"SELECT COUNT(*) FROM files f WHERE {where_sql}"

        count_params = {k: params[k] for k in params if k not in ("lim", "off")}
        with self._engine.connect() as conn:
            total = conn.execute(text(count_sql), count_params).scalar() or 0
            rows = conn.execute(text(select_sql), params).fetchall()

        return self._format_paged(rows, total, page, page_size)

    @staticmethod
    def _format_paged(rows, total, page, page_size) -> dict:
        items = []
        items_append = items.append
        for r in rows:
            raw_tags = r[6]
            if raw_tags:
                tags = [t for t in raw_tags.split(",") if t]
            else:
                tags = []
            items_append({
                "id": r[0], "path": r[1], "filename": r[2],
                "size_bytes": r[3] or 0, "size_human": r[4] or "",
                "category": r[5] or "other",
                "tags": tags,
                "has_thumbnail": bool(r[7]),
            })
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    # ── CLI search (returns dicts; used by search_db / print_summary) ───────

    def search_files(self, term: str, limit: int = 50,
                     scan_id: int | None = None,
                     category: str | None = None) -> list[dict]:
        if self.dialect == "sqlite":
            return self._sqlite_search(term, limit, scan_id, category)
        return self._pg_search(term, limit, scan_id, category)

    def _sqlite_search(self, term: str, limit: int,
                       scan_id: int | None, category: str | None) -> list[dict]:
        extra_where = ""
        params: dict = {"t": term, "lim": limit}
        if scan_id is not None:
            extra_where += " AND f.scan_id = :sid"
            params["sid"] = scan_id
        if category:
            extra_where += " AND f.category = :cat"
            params["cat"] = category

        with self._engine.connect() as conn:
            try:
                rows = conn.execute(
                    text(
                        "SELECT f.path, f.category, f.size_human, f.tags, f.scan_id "
                        "FROM files f JOIN files_fts fts ON fts.rowid = f.id "
                        "WHERE files_fts MATCH :t" + extra_where +
                        " ORDER BY fts.rank LIMIT :lim"
                    ),
                    params,
                ).fetchall()
                if rows:
                    return [{"path": r[0], "category": r[1],
                             "size_human": r[2], "tags": r[3],
                             "scan_id": r[4]} for r in rows]
            except OperationalError:
                pass
            # Fall back to LIKE when FTS is absent or produced no rows.
            like_params: dict = {"l": f"%{term}%", "lim": limit}
            like_extra = ""
            if scan_id is not None:
                like_extra += " AND scan_id = :sid"
                like_params["sid"] = scan_id
            if category:
                like_extra += " AND category = :cat"
                like_params["cat"] = category
            rows = conn.execute(
                text(
                    "SELECT path, category, size_human, tags, scan_id FROM files "
                    "WHERE (path LIKE :l OR filename LIKE :l "
                    "       OR category LIKE :l OR tags LIKE :l)" + like_extra +
                    " ORDER BY path LIMIT :lim"
                ),
                like_params,
            ).fetchall()
        return [{"path": r[0], "category": r[1],
                 "size_human": r[2], "tags": r[3],
                 "scan_id": r[4]} for r in rows]

    def _pg_search(self, term: str, limit: int,
                   scan_id: int | None, category: str | None) -> list[dict]:
        extra_where = ""
        params: dict = {"t": term, "lim": limit}
        if scan_id is not None:
            extra_where += " AND scan_id = :sid"
            params["sid"] = scan_id
        if category:
            extra_where += " AND category = :cat"
            params["cat"] = category
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT path, category, size_human, tags, scan_id FROM files "
                    "WHERE fts @@ plainto_tsquery('english', :t)" + extra_where +
                    " ORDER BY ts_rank(fts, plainto_tsquery('english', :t)) DESC LIMIT :lim"
                ),
                params,
            ).fetchall()
        return [{"path": r[0], "category": r[1],
                 "size_human": r[2], "tags": r[3],
                 "scan_id": r[4]} for r in rows]

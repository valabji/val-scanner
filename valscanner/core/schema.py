from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

scans = Table(
    "scans",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("label", Text, nullable=False, default=""),
    Column("root", Text, nullable=False),
    Column("scanned_at", Text, nullable=False),
    Column("file_count", Integer, default=0),
    Column("total_bytes", BigInteger, default=0),
    Column("total_human", Text, default=""),
    Column("status", Text, default="complete"),
)

files = Table(
    "files",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scan_id", Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("filename", Text, nullable=False),
    Column("extension", Text),
    Column("category", Text),
    Column("mime_type", Text),
    Column("size_bytes", BigInteger),
    Column("size_human", Text),
    Column("sha256", Text),
    Column("created_at", Text),
    Column("modified_at", Text),
    Column("accessed_at", Text),
    Column("is_hidden", Integer),
    Column("tags", Text),
    Column("extra_meta", Text),
    Column("indexed_at", Text),
    UniqueConstraint("scan_id", "path", name="uq_files_scan_path"),
    # Composite covering index for the hot web/GUI paged-list query:
    # WHERE scan_id = :sid AND category = :cat ORDER BY path
    Index("idx_files_scan_cat_path", "scan_id", "category", "path"),
    Index("idx_files_category", "category"),
    Index("idx_files_extension", "extension"),
    Index("idx_files_size", "size_bytes"),
    Index("idx_files_modified", "modified_at"),
)

folders = Table(
    "folders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scan_id", Integer, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False),
    Column("path", Text, nullable=False),
    Column("file_count", Integer, default=0),
    Column("total_bytes", BigInteger, default=0),
    Column("total_human", Text),
    Column("indexed_at", Text),
    UniqueConstraint("scan_id", "path", name="uq_folders_scan_path"),
    Index("idx_folders_size", "total_bytes"),
    Index("idx_folders_scan", "scan_id"),
)

thumbnails = Table(
    "thumbnails",
    metadata,
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True),
    Column("data", LargeBinary, nullable=False),
    Column("width", Integer),
    Column("height", Integer),
)

media_samples = Table(
    "media_samples",
    metadata,
    Column("file_id", Integer, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True),
    Column("data", LargeBinary, nullable=False),
    Column("format", Text),
    Column("duration", Float),
)

gui_cache = Table(
    "gui_cache",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value_json", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

# `scope_scan_ids` is intentionally NOT a separate column — it moves into
# filters_json under the key "scope_scan_ids" so we have one parser, not two.
analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ran_at", Text, nullable=False),
    Column("min_files", Integer, nullable=False),
    Column("threshold", Float, nullable=False),
    Column("scope_label", Text, nullable=False, default=""),
    Column("duration_ms", Integer, default=0),
    Column("pair_count", Integer, default=0),
    Column("filters_json", Text, nullable=False, default="{}"),
    Column("results_json", Text, nullable=False, default="[]"),
    Index("idx_analysis_ran_at", "ran_at"),
)

# ── SQLite FTS5 ───────────────────────────────────────────────────────────────

_FTS5_STMTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
        path, filename, category, tags,
        content='files', content_rowid='id'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
        INSERT INTO files_fts(rowid, path, filename, category, tags)
        VALUES (new.id, new.path, new.filename, new.category, new.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, path, filename, category, tags)
        VALUES ('delete', old.id, old.path, old.filename, old.category, old.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
        INSERT INTO files_fts(files_fts, rowid, path, filename, category, tags)
        VALUES ('delete', old.id, old.path, old.filename, old.category, old.tags);
        INSERT INTO files_fts(rowid, path, filename, category, tags)
        VALUES (new.id, new.path, new.filename, new.category, new.tags);
    END
    """,
]


def apply_sqlite_fts(connection) -> None:
    """Create FTS5 table + triggers on a SQLite connection.

    Idempotent (every statement uses IF NOT EXISTS). Safe to call from both
    `metadata.create_all` (via the event listener below) and from an Alembic
    migration. No-op on non-SQLite dialects.
    """
    if connection.dialect.name != "sqlite":
        return
    for stmt in _FTS5_STMTS:
        connection.execute(text(stmt.strip()))


@event.listens_for(files, "after_create")
def _files_after_create(target, connection, **_kw):
    apply_sqlite_fts(connection)


# ── PostgreSQL tsvector FTS ───────────────────────────────────────────────────

_PG_FTS_STMTS = [
    "ALTER TABLE files ADD COLUMN IF NOT EXISTS fts tsvector",

    "CREATE INDEX IF NOT EXISTS idx_files_fts ON files USING GIN(fts)",

    """
    CREATE OR REPLACE FUNCTION files_fts_update() RETURNS trigger AS $$
    BEGIN
        NEW.fts :=
            setweight(to_tsvector('english', translate(coalesce(NEW.filename, ''), '.', ' ')), 'A') ||
            setweight(to_tsvector('english', coalesce(NEW.category, '')),                       'B') ||
            setweight(to_tsvector('english', coalesce(NEW.tags, '')),                           'B') ||
            setweight(to_tsvector('english', translate(coalesce(NEW.path, ''), './', '  ')),    'C');
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,

    "DROP TRIGGER IF EXISTS files_fts_trigger ON files",

    """
    CREATE TRIGGER files_fts_trigger
        BEFORE INSERT OR UPDATE ON files
        FOR EACH ROW EXECUTE FUNCTION files_fts_update()
    """,
]


def apply_pg_fts(connection) -> None:
    """Add tsvector column, GIN index, function, and trigger.
    Idempotent. No-op on non-PostgreSQL dialects."""
    if connection.dialect.name != "postgresql":
        return
    for stmt in _PG_FTS_STMTS:
        connection.execute(text(stmt.strip()))


@event.listens_for(files, "after_create")
def _files_after_create_pg(target, connection, **_kw):
    apply_pg_fts(connection)


def create_all(engine: Engine) -> None:
    """Create all tables + FTS objects (no-op if they already exist).

    Steps 04 and 05 hook FTS DDL onto the `after_create` event of the `files`
    table, so calling this also sets up FTS for the active dialect.
    """
    metadata.create_all(engine, checkfirst=True)


def drop_all(engine: Engine) -> None:
    """Drop all tables (used in tests)."""
    metadata.drop_all(engine)


# ── helpers ──────────────────────────────────────────────────────────────────

def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def ts(epoch) -> str:
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")

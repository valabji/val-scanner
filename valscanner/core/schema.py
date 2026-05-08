from __future__ import annotations
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL DEFAULT '',
    root        TEXT    NOT NULL,
    scanned_at  TEXT    NOT NULL,
    file_count  INTEGER DEFAULT 0,
    total_bytes INTEGER DEFAULT 0,
    total_human TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id      INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    path         TEXT    NOT NULL,
    filename     TEXT    NOT NULL,
    extension    TEXT,
    category     TEXT,
    mime_type    TEXT,
    size_bytes   INTEGER,
    size_human   TEXT,
    sha256       TEXT,
    created_at   TEXT,
    modified_at  TEXT,
    accessed_at  TEXT,
    is_hidden    INTEGER,
    tags         TEXT,
    extra_meta   TEXT,
    indexed_at   TEXT,
    UNIQUE(scan_id, path)
);
CREATE INDEX IF NOT EXISTS idx_category  ON files(category);
CREATE INDEX IF NOT EXISTS idx_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_size      ON files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_modified  ON files(modified_at);
CREATE INDEX IF NOT EXISTS idx_scan_id   ON files(scan_id);

CREATE TABLE IF NOT EXISTS folders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    path          TEXT    NOT NULL,
    file_count    INTEGER DEFAULT 0,
    total_bytes   INTEGER DEFAULT 0,
    total_human   TEXT,
    indexed_at    TEXT,
    UNIQUE(scan_id, path)
);
CREATE INDEX IF NOT EXISTS idx_folder_size ON folders(total_bytes);
CREATE INDEX IF NOT EXISTS idx_folder_scan ON folders(scan_id);

CREATE TABLE IF NOT EXISTS thumbnails (
    file_id  INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    data     BLOB    NOT NULL,
    width    INTEGER,
    height   INTEGER
);

CREATE TABLE IF NOT EXISTS media_samples (
    file_id  INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    data     BLOB    NOT NULL,
    format   TEXT,
    duration REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    path, filename, category, tags, extra_meta,
    content='files', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, path, filename, category, tags, extra_meta)
    VALUES (new.id, new.path, new.filename, new.category, new.tags, new.extra_meta);
END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, path, filename, category, tags, extra_meta)
    VALUES ('delete', old.id, old.path, old.filename, old.category, old.tags, old.extra_meta);
END;
"""


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

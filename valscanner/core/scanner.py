from __future__ import annotations
import json
import mimetypes
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from .schema import SCHEMA, human_size, ts
from .categories import EXT_CATEGORY, MIME_CATEGORY
from .metadata import (
    extract_image_metadata, extract_audio_metadata, extract_pdf_metadata,
    file_sha256, _thumb_image, _thumb_video, _sample_media,
)
from .tagging import generate_tags


_SYSTEM_DIRS = frozenset({
    # macOS
    "System", "Library", "private", "usr", "bin", "sbin", "dev", "Volumes",
    "cores", "net", "home",
    # Windows
    "Windows", "System32", "SysWOW64", "Program Files", "Program Files (x86)",
    "ProgramData", "AppData", "Recovery", "MSOCache",
    # Linux
    "proc", "sys", "run", "snap",
})

_CACHE_DIRS = frozenset({
    "__pycache__", "node_modules", ".gradle", ".m2", ".ivy2",
    "build", "dist", ".next", ".nuxt", "target", ".tox",
    "venv", ".venv", "env", ".eggs", "site-packages",
    ".sass-cache", "coverage", ".nyc_output", "DerivedData",
    ".build", "Pods", "bower_components", ".yarn", ".pnpm-store",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_VCS_DIRS = frozenset({
    ".git", ".svn", ".hg", ".bzr", "_darcs", "CVS", ".fossil",
})

_BINARY_EXTS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib",
    ".obj", ".class", ".pyc", ".pyo", ".pyd", ".wasm",
    ".out", ".elf", ".ko", ".sys",
})

_TEMP_EXTS = frozenset({
    ".tmp", ".temp", ".swp", ".swo", ".swn", ".bak", ".orig",
    ".~lock", ".DS_Store",
})

_LOG_EXTS = frozenset({
    ".log",
})


def scan(
    root: Path,
    db_path: str,
    compute_hash: bool = True,
    verbose: bool = False,
    label: str = "",
    store_thumbnails: bool = False,
    thumb_size: int = 128,
    thumb_quality: int = 75,
    store_samples: bool = False,
    sample_duration: int = 5,
    skip_hidden_files: bool = False,
    skip_hidden_dirs:  bool = True,
    skip_system:       bool = False,
    skip_caches:       bool = False,
    skip_vcs:          bool = False,
    skip_binaries:     bool = False,
    skip_temp:         bool = False,
    skip_logs:         bool = False,
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_label = label.strip() or root.name

    cur.execute(
        "INSERT INTO scans (label, root, scanned_at) VALUES (?, ?, ?)",
        (scan_label, str(root), now),
    )
    scan_id = cur.lastrowid
    conn.commit()

    stats: dict = {"scanned": 0, "errors": 0, "skipped": 0, "scan_id": scan_id, "total_bytes": 0}
    folder_totals: dict = {}

    def _keep_dir(name: str) -> bool:
        if skip_hidden_dirs and name.startswith("."):
            return False
        if skip_vcs and name in _VCS_DIRS:
            return False
        if skip_system and name in _SYSTEM_DIRS:
            return False
        if skip_caches and name in _CACHE_DIRS:
            return False
        return True

    def _keep_file(name: str, ext: str) -> bool:
        if skip_hidden_files and name.startswith("."):
            return False
        if skip_binaries and ext in _BINARY_EXTS:
            return False
        if skip_temp and (ext in _TEMP_EXTS or name == ".DS_Store"):
            return False
        if skip_logs and ext in _LOG_EXTS:
            return False
        return True

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if _keep_dir(d)]

        for fname in filenames:
            ext_check = Path(fname).suffix.lower()
            if not _keep_file(fname, ext_check):
                stats["skipped"] += 1
                continue
            fpath = Path(dirpath) / fname
            try:
                st       = fpath.stat()
                size     = st.st_size
                ext      = fpath.suffix.lower()
                mime, _  = mimetypes.guess_type(str(fpath))
                category = EXT_CATEGORY.get(ext)
                if not category and mime:
                    category = MIME_CATEGORY.get(mime.split("/")[0], "other")
                if not category:
                    category = "other"

                extra: dict = {}
                if category == "photo":
                    extra.update(extract_image_metadata(fpath))
                elif category == "audio":
                    extra.update(extract_audio_metadata(fpath))
                elif ext == ".pdf":
                    extra.update(extract_pdf_metadata(fpath))

                tags    = generate_tags(fpath, category, size)
                sha     = file_sha256(fpath) if compute_hash else ""
                created = getattr(st, "st_birthtime", st.st_ctime)

                row = {
                    "scan_id":     scan_id,
                    "path":        str(fpath.resolve()),
                    "filename":    fname,
                    "extension":   ext or "(none)",
                    "category":    category,
                    "mime_type":   mime or "",
                    "size_bytes":  size,
                    "size_human":  human_size(size),
                    "sha256":      sha,
                    "created_at":  ts(created),
                    "modified_at": ts(st.st_mtime),
                    "accessed_at": ts(st.st_atime),
                    "is_hidden":   int(fname.startswith(".")),
                    "tags":        ", ".join(tags),
                    "extra_meta":  json.dumps(extra) if extra else "",
                    "indexed_at":  now,
                }

                cur.execute("""
                    INSERT OR REPLACE INTO files
                    (scan_id,path,filename,extension,category,mime_type,size_bytes,size_human,
                     sha256,created_at,modified_at,accessed_at,is_hidden,tags,extra_meta,indexed_at)
                    VALUES
                    (:scan_id,:path,:filename,:extension,:category,:mime_type,:size_bytes,:size_human,
                     :sha256,:created_at,:modified_at,:accessed_at,:is_hidden,:tags,:extra_meta,:indexed_at)
                """, row)
                file_id = cur.lastrowid

                if store_thumbnails:
                    thumb = None
                    if category in ("photo", "image"):
                        thumb = _thumb_image(fpath, thumb_size, thumb_quality)
                    elif category == "video":
                        thumb = _thumb_video(fpath, thumb_size, thumb_quality)
                    if thumb:
                        cur.execute(
                            "INSERT OR REPLACE INTO thumbnails (file_id, data) VALUES (?, ?)",
                            (file_id, thumb),
                        )

                if store_samples and category in ("audio", "video"):
                    sample = _sample_media(fpath, category, sample_duration)
                    if sample:
                        data, fmt = sample
                        cur.execute(
                            "INSERT OR REPLACE INTO media_samples (file_id, data, format, duration)"
                            " VALUES (?, ?, ?, ?)",
                            (file_id, data, fmt, sample_duration),
                        )

                stats["scanned"]     += 1
                stats["total_bytes"] += size

                folder = Path(dirpath).resolve()
                while True:
                    key = str(folder)
                    if key not in folder_totals:
                        folder_totals[key] = [0, 0]
                    folder_totals[key][0] += 1
                    folder_totals[key][1] += size
                    if folder == root:
                        break
                    parent = folder.parent
                    if parent == folder:
                        break
                    folder = parent

                if verbose:
                    print(f"  [{category:14s}] {fpath}")

            except (PermissionError, FileNotFoundError, OSError) as e:
                stats["errors"] += 1
                if verbose:
                    print(f"  [ERROR] {fpath}: {e}")

    for fpath_str, (fc, tb) in folder_totals.items():
        cur.execute("""
            INSERT OR REPLACE INTO folders (scan_id, path, file_count, total_bytes, total_human, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (scan_id, fpath_str, fc, tb, human_size(tb), now))

    cur.execute(
        "UPDATE scans SET file_count=?, total_bytes=?, total_human=? WHERE id=?",
        (stats["scanned"], stats["total_bytes"], human_size(stats["total_bytes"]), scan_id),
    )
    conn.commit()
    conn.close()
    return stats

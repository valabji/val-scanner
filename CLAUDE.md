# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with optional deps)
pip install -e ".[rich]"
pip install -e ".[web]"        # adds fastapi + uvicorn
cd web-ui && npm install && cd ..

# Run the GUI app (Qt)
python -m valscanner.gui.window     # or: valscanner-gui

# Run the CLI scanner
valscanner /path/to/scan
valscanner /path/to/scan --db my.db --no-hash --export-csv --export-json --verbose
valscanner --list-scans --db my.db
valscanner --delete-scan 3 --db my.db

# Run the Web UI (development — two terminals)
valscanner-web --db my.db --dev    # terminal 1 — Python API on :7070
cd web-ui && npm run dev            # terminal 2 — Vite on :5173

# Run the Web UI (production)
./scripts/build_web.sh              # builds SPA into valscanner/web/static/
valscanner-web --db my.db           # serves built app on :7070
```

## Architecture

### Package layout

```
myscanner/                  ← repo root
├── pyproject.toml          ← packaging & entry points (valscanner, valscanner-gui)
├── valscanner.spec         ← PyInstaller spec
├── app_entry.py            ← PyInstaller entry point
├── scripts/                ← build, install, and version-bump helpers
│
└── valscanner/             ← installable Python package
    ├── cli.py              ← CLI entry point: valscanner
    │
    ├── core/               ← zero Qt dependencies
    │   ├── schema.py       ← SCHEMA DDL, human_size(), ts()
    │   ├── categories.py   ← EXT_CATEGORY, MIME_CATEGORY
    │   ├── metadata.py     ← extract_image/audio/pdf, _thumb_*, _sample_media, file_sha256
    │   ├── tagging.py      ← generate_tags()
    │   ├── scanner.py      ← scan()
    │   ├── similarity.py   ← find_similar_folders(), math helpers
    │   ├── export.py       ← export_csv(), export_json()
    │   └── db.py           ← query_db(), print_summary(), list_scans(), delete_scan()
    │
    └── gui/                ← PySide6 front-end
        ├── constants.py    ← CATEGORY_COLORS, DARK_BG, PANEL_BG, …
        ├── workers.py      ← ScanWorker, AnalysisWorker (QThread)
        ├── models.py       ← FileTableModel, FileIconModel, ThumbnailCache
        ├── delegates.py    ← FileCardDelegate, FileRowDelegate
        ├── dialogs.py      ← ScanOptionsDialog
        ├── window.py       ← MainWindow + main() — GUI entry point: valscanner-gui
        └── panels/
            ├── detail.py   ← DetailPanel, TagChip, FlowLayout
            ├── folders.py  ← FolderPanel
            ├── similar.py  ← SimilarFoldersPanel, FolderPairCard
            ├── scans.py    ← ScansPanel
            └── console.py  ← ConsolePanel, _StderrBridge
```

### Core layer (valscanner/core/)

- **schema.py** — SQLite DDL for `scans`, `files`, `folders`, `thumbnails`, `media_samples`, and the FTS5 virtual table + triggers
- **scanner.py** — `scan(root, db_path, …)` walks a directory tree, writes every file as a row into SQLite, accumulates folder totals
- **similarity.py** — pairwise folder comparison using a weighted blend of filename Jaccard, extension cosine, size ratio, and SHA-256 Jaccard; returns a hierarchy (sub-pairs nested under ancestor pairs)
- **metadata.py** — optional-library feature detection at import time; extractors silently return `{}` if their library is absent
- **tagging.py** — rule-based tag generation from path parts, filename keywords, size, and extension

### GUI layer (valscanner/gui/)

- **workers.py** — `ScanWorker` monkey-patches `os.walk` to emit per-file progress signals; `AnalysisWorker` runs `find_similar_folders` in background
- **models.py** — `FileTableModel` (flat list, raw `size_bytes` for numeric sort), `FileIconModel`, `ThumbnailCache` singleton `_THUMB_CACHE`
- **delegates.py** — `FileCardDelegate` (grid view), `FileRowDelegate` (compact list)
- **panels/folders.py** — `FolderPanel` tree view; uses `QSortFilterProxyModel` with `Qt.UserRole+1` for numeric sort
- **panels/similar.py** — collapsible `FolderPairCard` cards; child pairs display relative paths via `Path.relative_to()`
- **panels/detail.py** — right-side file inspector; tags as `TagChip` labels

## Database schema

Five tables in every `.db` file:
- `scans` — one row per scan session; tracks label, root, file count, total size
- `files` — one row per file; `extra_meta` is a JSON blob of rich metadata
- `folders` — cumulative byte/file counts for every ancestor directory up to the scan root
- `thumbnails` — JPEG blobs keyed by `file_id`
- `media_samples` — low-quality audio/video clips keyed by `file_id`
- `files_fts` — FTS5 virtual table mirroring `files`; populated by `AFTER INSERT` / `AFTER DELETE` triggers

## Git workflow rules

- **Create a branch first** — before making any code changes, create and check out a new feature branch: `git checkout -b claude-<short-descriptive-name>`; branch names must always start with `claude-`; never work directly on `main`; **exception**: if the current branch name already starts with `claude`, skip branch creation and commit directly to it
- **Commit after completing work** — once a logical unit of work is done, stage the changed files and commit with a single-line imperative message (≤50 chars); never include a `Co-Authored-By` trailer or any multi-line body; suggest the exact `git commit` command to the user to run themselves
- **Never push** — do not run `git push` or any destructive git command
- **Warn on dirty working tree** — before editing any file, run `git status` and warn the user if there are uncommitted changes; do not proceed until the user acknowledges

## Key design notes

- `*.db`, `*.csv`, and `*.json` are gitignored — output files are never committed
- Optional libraries (Pillow, mutagen, PyPDF2) are detected at import time via `try/except`; the scanner runs without them, just without rich metadata
- Hidden directories (names starting with `.`) are pruned from `os.walk` in `scan()`; hidden *files* are indexed but tagged `hidden-file`/`dotfile`
- The similarity algorithm weights differ depending on whether any SHA-256 hashes exist in the DB (`has_hashes` flag)
- Run the GUI directly with `python -m valscanner.gui.window` or the installed `valscanner-gui` entry point

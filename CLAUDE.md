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

## Shell command policy (do not trigger permission prompts)

You may run only commands that are either (a) Claude Code's built-in auto-allowed set, or (b) listed in `.claude/settings.local.json` under `permissions.allow`. Anything outside that set will trigger an interactive prompt — **don't do it**. If a task genuinely requires a different command, stop and ask the user to extend the allowlist first; do not attempt the command and absorb the prompt.

### Auto-allowed (no allowlist entry required)
- **Read-only file ops (any args):** `cat`, `head`, `tail`, `wc`, `stat`, `nl`, `cut`, `tr`, `tac`, `rev`, `fold`, `comm`, `diff`, `cmp`, `od`, `hexdump`, `strings`, `basename`, `dirname`, `realpath`, `readlink`, `numfmt`, `ls`, `find`, `cd`, `expand`, `unexpand`, `fmt`, `paste`, `column`, `pr`.
- **Read-only system info (any args):** `id`, `uname`, `groups`, `locale`, `nproc`, `free`, `df`, `du`, `getconf`, `true`, `false`, `sleep`, `which`, `type`, `expr`, `test`, `seq`, `tsort`, `echo`, `printf`, `cal`, `uptime`.
- **Zero-arg only:** `pwd`, `whoami`, `alias`.
- **Safe flags only (run a sanity check first if unsure):** `grep`, `egrep`, `fgrep`, `rg`, `fd`, `fdfind`, `jq`, `sort`, `uniq`, `xargs`, `file`, `sed` (read-only expressions), `base64`, `sha256sum`, `sha1sum`, `md5sum`, `tree`, `date`, `hostname`, `history`, `ps`, `pgrep`, `lsof`, `netstat`, `ss`, `tput`, `ifconfig`, `arch`, `man`, `help`, `info`, `pyright`.
- **All git read-only subcommands:** `git status`, `git log`, `git diff`, `git show`, `git blame`, `git branch`, `git tag`, `git remote`, `git ls-files`, `git ls-remote`, `git config --get`, `git rev-parse`, `git describe`, `git stash list`, `git reflog`, `git shortlog`, `git cat-file`, `git for-each-ref`, `git worktree list`.
- **All gh read-only subcommands:** `gh pr view|list|diff|checks|status`, `gh issue view|list|status`, `gh run view|list`, `gh workflow view|list`, `gh repo view`, `gh release view|list`, `gh api` (GET only), `gh auth status`.
- **Exact-form only:** `node -v`, `node --version`, `python --version`, `python3 --version`, `ip addr`, `claude -h`, `claude --help`.

### Project-allowed

Read `.claude/settings.local.json` (the `permissions.allow` array) for the current set — it changes over time, so don't rely on a hardcoded copy here. Treat every entry as the literal pattern that would match: an exact form like `Bash(mkdir -p /tmp/vs_fixture)` covers **that command only**, while `Bash(git *)` covers any `git …` invocation.

Caveats that override the allowlist:
- `Bash(git *)` is broad, but the Git workflow rules below still forbid `git push`, `git reset --hard`, and other destructive operations.
- Narrow `rm` / `mkdir` entries are scoped to specific paths — do not generalize them to other paths.
- Prefer the `Read` / `Edit` / `Write` tools over shell equivalents (`cat`, `sed -i`, `tee`) regardless of what's allowlisted.

### When the right tool isn't allowlisted

Reach for a covered alternative first:

| Want to do | Use instead of |
|---|---|
| Inspect a file | `Read` tool (or auto-allowed `cat`/`head`/`tail`) — not `less`/`more`/`bat` |
| Edit a file | `Edit`/`Write` tool — not `sed -i`/`tee`/`>` redirection |
| Search code | `grep`/`rg` (auto-allowed) — not custom shell loops |
| List directory tree | `ls`/`find`/`tree` (auto-allowed) — not `du -a` workarounds |
| Delete a temp file | Work inside `/tmp/vs_fixture` (the one allowed `rm` target) |
| Install a new dep | `pip install …` or `npm install …` (both allowlisted) |
| Anything else | **Skip silently and keep working.** Don't run the command, don't pop a permission prompt, don't interrupt to ask. Collect the missing pattern in an end-of-turn "permissions to consider" bullet so the user can extend the allowlist on their own schedule. Only halt the whole task if the missing capability genuinely blocks progress — and even then, propose the allowlist entry first instead of running the command. |

## Architecture

### Package layout

```
val-scanner/                ← repo root
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

- **schema.py** — SQLAlchemy table definitions (`scans`, `files`, `folders`, `thumbnails`, `media_samples`, `gui_cache`, `analysis_runs`) plus dialect-specific FTS bootstrap: `apply_sqlite_fts()` builds the FTS5 virtual table + triggers on SQLite; `apply_postgres_fts()` builds the `tsvector` column + GIN index on PostgreSQL. Both are no-ops on the other dialect.
- **db_config.py** — engine factory + per-URL cache; sets SQLite pragmas (`foreign_keys`, WAL, busy_timeout) on connect, uses `pool_pre_ping` for PostgreSQL
- **app_settings.py** — `active_url()` resolves the SQLAlchemy URL from (1) explicit override, (2) `DATABASE_URL` env var, (3) settings file (`db_backend`, `sqlite_path`, or `pg_*` fields with password from keyring), (4) built-in default `sqlite:///~/valscanner.db`
- **scanner.py** — `scan(root, db_path, …)` walks a directory tree, writes every file as a row, accumulates folder totals; `db_path` may be a filesystem path or a full SQLAlchemy URL
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

The schema is backend-agnostic (SQLAlchemy Core) and supported on both **SQLite** (default — single `.db` file) and **PostgreSQL** (selected via `db_backend=postgresql` in settings or `DATABASE_URL`). Alembic owns migrations (`alembic_version` table is present on both backends).

Tables:
- `scans` — one row per scan session; tracks label, root, file count, total size
- `files` — one row per file; `extra_meta` is a JSON blob of rich metadata
- `folders` — cumulative byte/file counts for every ancestor directory up to the scan root
- `thumbnails` — JPEG blobs keyed by `file_id`
- `media_samples` — low-quality audio/video clips keyed by `file_id`
- `gui_cache` — key/value JSON store for cached GUI state (versioned by `version` column)
- `analysis_runs` — history of similarity-analysis runs (filters, threshold, results) for the Similar Folders panel

Full-text search is set up per dialect by `apply_fts()`:
- **SQLite**: `files_fts` FTS5 virtual table mirroring `files`, populated by `AFTER INSERT` / `AFTER DELETE` triggers
- **PostgreSQL**: `files.fts` `tsvector` column with a GIN index, maintained by trigger

Reclaiming space on PostgreSQL: `DELETE` leaves dead tuples behind — run `VACUUM FULL <table>` (rewrites table, returns space to OS) or `TRUNCATE` to wipe and reset, since plain `VACUUM` only marks the space reusable.

## Git workflow rules

- **Create a branch first** — before making any code changes, create and check out a new feature branch: `git checkout -b claude-<short-descriptive-name>`; branch names must always start with `claude-`; never work directly on `main`; **exception**: if the current branch name already starts with `claude`, skip branch creation and commit directly to it
- **Commit after completing work** — once a logical unit of work is done, stage the changed files and commit with a single-line imperative message (≤50 chars); never include a `Co-Authored-By` trailer or any multi-line body; suggest the exact `git commit` command to the user to run themselves
- **Never push** — do not run `git push` or any destructive git command
- **Warn on dirty working tree** — before editing any file, run `git status` and warn the user if there are uncommitted changes; do not proceed until the user acknowledges

## Release discipline

ValScanner is on PyPI. Each merged UX-plan step is potentially a patch
release. Before publishing a new version:

1. Read `release-notes/CHECKLIST.md` and tick every item.
2. Author `release-notes/vX.Y.Z.md` from `release-notes/TEMPLATE.md`,
   pulling bullets from each shipped step's "Release notes" section.
3. Step 17 (settings migration) and step 10 (persistence) **always
   ship in the same release**. Step 12 (terminology lock) **always
   ships alone**.

When uncertain about cadence, ship smaller, more often.

## Key design notes

- `*.db`, `*.csv`, and `*.json` are gitignored — output files are never committed
- Optional libraries (Pillow, mutagen, pypdf) are detected at import time via `try/except`; the scanner runs without them, just without rich metadata
- Hidden directories (names starting with `.`) are pruned from `os.walk` in `scan()`; hidden *files* are indexed but tagged `hidden-file`/`dotfile`
- The similarity algorithm weights differ depending on whether any SHA-256 hashes exist in the DB (`has_hashes` flag)
- Run the GUI directly with `python -m valscanner.gui.window` or the installed `valscanner-gui` entry point
- **User-facing terminology** is locked by `local_plans/02_ux_enhancements/GLOSSARY.md`. When adding strings to the GUI, match the canonical forms. Code identifiers may drift; user-facing strings must not.

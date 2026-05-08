# ValScanner

A recursive file scanner with rich metadata extraction, full-text search, auto-tagging, thumbnail generation, and similar-folder detection — available as both a CLI tool and a PySide6 GUI.

---

## Features

- **Recursive scan** — indexes every file under a root directory into a local SQLite database
- **Rich metadata** — image EXIF, audio tags, PDF page count (optional deps: Pillow, mutagen, PyPDF2)
- **Thumbnails** — JPEG blobs stored in-database; shown in GUI grid view (requires Pillow or ffmpeg)
- **Media samples** — short low-quality audio/video clips stored in-database (requires ffmpeg)
- **Auto-tagging** — rule-based tags from path keywords, filename, size bucket, and extension
- **Full-text search** — FTS5 virtual table over filenames and paths; live search in the GUI
- **Similar-folder detection** — pairwise comparison using filename Jaccard + extension cosine + size ratio + SHA-256 Jaccard
- **View filters** — slice the result set by category, size range, extension, or path pattern without re-scanning
- **Export** — CSV and JSON from both CLI and GUI
- **Multiple scan sessions** — each scan stored with a label; compare, list, or delete past sessions

---

## Requirements

| Requirement | Version | Role |
|---|---|---|
| Python | 3.8+ | runtime |
| PySide6 | any recent | GUI |
| Pillow *(optional)* | any | image EXIF + thumbnails |
| mutagen *(optional)* | any | audio metadata (artist, album, duration, …) |
| PyPDF2 *(optional)* | any | PDF page count |
| ffmpeg *(optional)* | any | video thumbnails + media samples |

---

## Installation

### pipx (recommended for most users)

```bash
# Install from PyPI — both CLI and GUI available immediately
pipx install valscanner

valscanner /path/to/scan      # CLI
valscanner-gui                # GUI
```

Run once without installing:

```bash
pipx run valscanner /path/to/scan
pipx run --spec valscanner valscanner-gui
```

### macOS / Linux (from source)

```bash
git clone <repo-url> valscanner
cd valscanner

# Full install — creates .venv, installs all deps, symlinks launchers to ~/.local/bin
bash scripts/install.sh

# Skip optional rich-metadata deps (faster scan, no EXIF/audio/PDF)
bash scripts/install.sh --no-rich

# Install into your active Python environment instead of a new venv
bash scripts/install.sh --no-venv

# Choose where launcher symlinks go
bash scripts/install.sh --prefix /usr/local
```

### Windows (from source)

```powershell
git clone <repo-url> valscanner
cd valscanner

# Full install — creates .venv, writes .cmd launchers to %LOCALAPPDATA%\Programs\ValScanner\bin
.\scripts\install.ps1

# Skip optional deps
.\scripts\install.ps1 -NoRich

# Install into your active Python environment
.\scripts\install.ps1 -NoVenv

# Choose launcher directory
.\scripts\install.ps1 -Prefix "C:\Tools\ValScanner"
```

### pip (manual)

```bash
pip install valscanner              # CLI + GUI
pip install "valscanner[rich]"      # + image EXIF / audio tags / PDF metadata
```

---

## Quick Start

```bash
# Index your Downloads folder
valscanner ~/Downloads

# Open the result in the GUI
valscanner-gui
```

The GUI will load your most recent scan automatically. Switch between grid and list view, search by filename, filter by category or size, and inspect any file in the detail panel on the right.

---

## CLI Usage

### Basic scan

```bash
valscanner /path/to/scan
```

Writes results to `file_index.db` in the current directory. Prints a summary when done:

```
✅ Done in 4.2s — scan #1, 12,847 indexed, 0 errors, 3 skipped
```

### Named scans

Use `--label` to tag a scan session with a human-readable name. Useful when you scan the same root repeatedly over time:

```bash
valscanner ~/Documents --label "docs-before-cleanup"
valscanner ~/Documents --label "docs-after-cleanup"
valscanner --list-scans
```

```
[  1]  docs-before-cleanup       14,201 files     2.1 GB  2026-05-01 09:12
[  2]  docs-after-cleanup        11,088 files     1.6 GB  2026-05-17 14:30
```

### Fast scan (skip hashing)

SHA-256 hashing is the slowest part of a scan. Skip it when you only need the file index, not exact-duplicate detection:

```bash
valscanner /large/drive --no-hash
```

Note: the similar-folder algorithm uses a lighter similarity model when hashes are absent, relying on filenames, extensions, and sizes instead.

### Search after scanning

```bash
valscanner /path --query "invoice"
```

Runs an FTS5 query against the database and prints matching files after the scan completes. You can also query an existing database without re-scanning:

```bash
valscanner --query "contract" --db my.db --list-scans
```

### Export results

```bash
# Export to CSV and JSON in one pass
valscanner ~/Projects --export-csv --export-json --db projects.db

# Resulting files: projects.csv, projects.json
```

The CSV contains one row per file with all indexed columns. The JSON is an array of the same objects, useful for piping into `jq` or loading into pandas.

### Verbose mode

Print each file path as it is indexed — useful to verify what is being included or skipped:

```bash
valscanner /path --verbose
```

### Manage scan history

```bash
# List all scans stored in a database
valscanner --list-scans --db archive.db

# Delete a specific scan (removes its files, folders, thumbnails, and media samples)
valscanner --delete-scan 3 --db archive.db
```

### Full flag reference

| Flag | Default | Description |
|---|---|---|
| `path` | — | Root directory to scan (required unless using `--list-scans` or `--delete-scan`) |
| `--db PATH` | `file_index.db` | SQLite database file to write to / read from |
| `--label NAME` | *(timestamp)* | Human-readable label for this scan session |
| `--no-hash` | off | Skip SHA-256 hashing (faster; lighter similarity model) |
| `--export-csv` | off | Write `<db-name>.csv` after scan |
| `--export-json` | off | Write `<db-name>.json` after scan |
| `--query TERM` | — | FTS5 query to run against the database after scanning |
| `--verbose` / `-v` | off | Print each file path as it is indexed |
| `--list-scans` | — | Print all scans in the database and exit |
| `--delete-scan ID` | — | Delete a scan by numeric ID and exit |

---

## GUI Usage

Launch the GUI:

```bash
valscanner-gui
# or via pipx
pipx run --spec valscanner valscanner-gui
```

### Starting a scan

Click **Scan** in the toolbar or go to **File → Scan Directory**. A file picker opens; choose a root directory. Then click **Options** (or the gear icon) before confirming to configure the scan.

### Scan Options dialog

| Option | What it does |
|---|---|
| **Store thumbnails** | Saves a JPEG thumbnail per image/video file into the database. Shown in grid view. Requires Pillow (images) or ffmpeg (video). |
| **Thumbnail size** | Max pixel dimension (32–512 px, default 128 px) |
| **JPEG quality** | Compression quality for stored thumbnails (40–95%, default 75%) |
| **Store media samples** | Saves a short low-quality clip per audio/video file (32 kbps MP3 / 240p MP4). Requires ffmpeg. |
| **Sample duration** | Length of each media sample (1–30 s, default 5 s) |

**Folder filters** (applied during scan — excluded folders are never indexed):

| Filter | Skips |
|---|---|
| Hidden folders | Any directory whose name starts with `.` |
| Version control | `.git`, `.svn`, `.hg`, and similar VCS directories |
| System folders | `Windows`, `System32`, `Library`, `/proc`, `/sys`, and similar |
| Cache & build dirs | `node_modules`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, and similar |

**File filters** (applied during scan — excluded files are never indexed):

| Filter | Skips |
|---|---|
| Hidden files | Any file whose name starts with `.` |
| Binary / compiled | `.exe`, `.dll`, `.so`, `.pyc`, `.o`, `.a`, and similar |
| Temporary files | `.tmp`, `.bak`, `.swp`, `.DS_Store`, and similar |
| Log files | `.log` |

### Browsing results

After a scan completes, the file list populates immediately. Use:

- **Grid view** — shows thumbnails for images and videos; cards display name, size, and category colour
- **List view** — compact rows; sortable by name, size, category, or extension; numeric sort for size
- **Search bar** — full-text search over filenames and paths (FTS5); results update as you type
- **Folder tree** (left panel) — click any folder to filter the file list to that directory; hold Shift and click for a recursive filter
- **Detail panel** (right panel) — click any file to see its full path, size, category, extension, tags, EXIF/audio metadata, and thumbnail

### View Filters dialog

**View → Filters** opens a live, non-modal filter panel. Changes apply instantly without re-scanning.

**Categories** — toggle any combination of the 14 file categories:

`archive` · `audio` · `code` · `data` · `document` · `ebook` · `executable` · `font` · `image` · `other` · `photo` · `presentation` · `spreadsheet` · `video`

Use **Select all** / **Select none** buttons to quickly isolate a single category.

**Size range** — enter a min and/or max file size with a unit (B / KB / MB / GB). Example: show only files between 10 MB and 2 GB.

**Extensions** — comma-separated list of extensions to show. Leave empty for all. Example: `jpg, png, webp` shows only those three.

**Path & file filters** — same folder/file filter options as the Scan Options dialog, but applied to the current view in real time (no re-scan needed):

- Hide hidden folders / VCS dirs / system folders / cache dirs
- Hide hidden files / binary files / temp files / log files

Click **Reset all filters** to return to the unfiltered view.

### Similar folders panel

**View → Similar Folders** (or the tab on the left) runs a background analysis comparing every folder pair in the scan using a weighted blend of:

- Filename Jaccard similarity
- Extension cosine similarity
- Size ratio
- SHA-256 Jaccard similarity *(only when hashes exist)*

Results are shown as collapsible cards. Each card shows the two folder paths, their similarity score, and — if one folder is a subfolder of the other — the relative path. Child pairs nest under ancestor pairs.

### Exporting from the GUI

**File → Export CSV** / **File → Export JSON** writes the current scan to a file of your choice.

---

## Scenarios

### "My Downloads folder is a mess"

```bash
valscanner ~/Downloads --label downloads-audit --export-csv
```

Open the CSV in a spreadsheet. Sort by `size_bytes` descending to find the largest files, or filter `category = video` to see what's eating space. In the GUI, use **View Filters → Categories** to hide everything except `video` and `archive`, then check the Folder tree for clusters.

### "Index my entire photo library"

```bash
pip install "valscanner[rich]"   # ensure Pillow is present
valscanner ~/Pictures --label photos-2026 --db photos.db
valscanner-gui
```

In the GUI, enable **Store thumbnails** before scanning so the grid view shows image previews. Filter by category `photo` or `image`, then use the size filter (e.g. Min 5 MB) to find RAW files. Click any file in the detail panel to read its EXIF (camera model, date taken, GPS, dimensions).

### "Find near-duplicate folders before migrating to a NAS"

```bash
valscanner /Volumes/OldDrive --label old-drive --db migration.db
```

After the scan, open the **Similar Folders** tab. Cards with a score above 0.8 are strong duplicate candidates. Expand each card to compare the two folder paths and decide which to keep.

### "Audit a project repo before archiving"

```bash
valscanner ~/Projects/acme --label acme-audit --no-hash
```

Open **View Filters** and enable **Hide: cache & build dirs** and **Hide: binary / compiled** to strip out noise. Switch to the **Folder tree** panel to see which subdirectories are heaviest. Use **View Filters → Extensions**: `log` to quickly check how much log data is checked in.

### "Compare a drive before and after a cleanup"

```bash
valscanner /Volumes/Drive --label before --db drive.db
# ... do your cleanup ...
valscanner /Volumes/Drive --label after  --db drive.db
valscanner --list-scans --db drive.db
```

Both scans share the same `.db` file. In the GUI, use the **Scans** panel to switch between them and compare totals.

### "Quick search without opening the GUI"

```bash
# Find all files matching "contract" in an existing database
valscanner --query contract --db ~/Documents/docs.db --list-scans
```

---

## Auto-generated tags

Every file receives a set of tags automatically. Tags are visible in the detail panel and exported with the file record.

**Category tags**

| Category | Tags added |
|---|---|
| `photo` | `photo`, `photos`, `media` |
| `video` / `audio` | `video` / `audio`, `media` |
| `document` / `spreadsheet` / `presentation` / `ebook` | category name, `documents` |
| `code` | `code`, `source-code`, `lang-<ext>` (e.g. `lang-py`) |
| `archive` | `archive`, `compressed` |
| `executable` | `executable`, `binary` |

**Size tags**

| Tag | File size |
|---|---|
| `empty-file` | 0 bytes |
| `tiny` | < 10 KB |
| `small` | 10 KB – 1 MB |
| `medium` | 1 MB – 100 MB |
| `large` | 100 MB – 1 GB |
| `huge` | > 1 GB |

**Folder keyword tags** — applied when the file's path contains a known folder name:

`downloads-folder` · `desktop-folder` · `documents-folder` · `pictures-folder` · `music-folder` · `videos-folder` · `backup` · `archived` · `old-files` · `temp-files` · `cached` · `log-files` · `work` · `projects` · `personal` · `private` · `shared` · `screenshots` · `wallpapers` · `fonts` · `assets` · `source-code` · `binaries` · `libraries` · `node-modules` · `python-venv` · `git-repo`

**Filename keyword tags** — applied when the filename contains a known keyword:

`resume` · `invoice` · `receipt` · `contract` · `screenshot` · `wallpaper` · `backup` · `draft` · `final-version` · `readme` · `changelog` · `license` · `build-file` · `docker` · `installer` · `config-file` · `log-file` · `test-file` · `notes` · `todo` · `report` · `summary` · `budget` · `sensitive`

**Extension tags**

| Extensions | Tag |
|---|---|
| `.jpg` `.jpeg` `.heic` `.heif` `.raw` `.cr2` `.nef` | `camera-photo` |
| `.png` `.svg` `.webp` | `graphic` |
| `.mp4` `.mov` `.m4v` | `modern-video` |
| `.mp3` `.flac` `.m4a` `.aac` | `music-file` |

**Other tags**: `hidden-file`, `dotfile` (files starting with `.`)

---

## Database schema

Every `.db` file contains six tables:

| Table | Contents |
|---|---|
| `scans` | One row per scan session (label, root, file count, total size, timestamp) |
| `files` | One row per file; `extra_meta` is a JSON blob of rich metadata (EXIF, audio tags, etc.) |
| `folders` | Cumulative byte/file counts for every ancestor directory up to the scan root |
| `thumbnails` | JPEG blobs keyed by `file_id` |
| `media_samples` | Low-quality audio/video clips keyed by `file_id` |
| `files_fts` | FTS5 virtual table mirroring `files`; populated by `AFTER INSERT` / `AFTER DELETE` triggers |

The database is plain SQLite — query it directly with any SQLite client:

```bash
sqlite3 file_index.db "SELECT name, size_bytes, category FROM files ORDER BY size_bytes DESC LIMIT 20"
```

---

## Project layout

```
valscanner/
├── pyproject.toml          ← packaging & entry points
├── valscanner.spec         ← PyInstaller spec (native app)
├── app_entry.py            ← PyInstaller entry point
├── scripts/
│   ├── build_app.sh        ← macOS/Linux native app builder
│   ├── build_app.ps1       ← Windows native app builder
│   ├── install.sh          ← macOS/Linux installer
│   ├── install.ps1         ← Windows PowerShell installer
│   └── bump_version.py     ← update version across all files
│
└── valscanner/
    ├── cli.py              ← CLI entry point (valscanner)
    ├── core/               ← zero Qt dependencies
    │   ├── schema.py       ← DDL, human_size(), ts()
    │   ├── categories.py   ← extension → category mapping
    │   ├── metadata.py     ← EXIF, audio, PDF extractors
    │   ├── tagging.py      ← generate_tags()
    │   ├── scanner.py      ← scan()
    │   ├── similarity.py   ← find_similar_folders()
    │   ├── export.py       ← export_csv(), export_json()
    │   └── db.py           ← query_db(), list_scans(), delete_scan()
    └── gui/                ← PySide6 front-end (valscanner-gui)
        ├── window.py       ← MainWindow
        ├── workers.py      ← ScanWorker, AnalysisWorker (QThread)
        ├── models.py       ← FileTableModel, FileIconModel, ThumbnailCache
        ├── delegates.py    ← FileCardDelegate (grid), FileRowDelegate (list)
        ├── dialogs.py      ← ScanOptionsDialog, ViewFiltersDialog
        └── panels/
            ├── detail.py   ← file inspector (tags, metadata, thumbnail)
            ├── folders.py  ← folder tree
            ├── similar.py  ← similar-folder cards
            ├── scans.py    ← scan session switcher
            └── console.py  ← stderr bridge / log output
```

---

## Development

```bash
# Editable install with all optional extras
pip install -e ".[rich]"

# Run without installing
python -m valscanner.gui.window    # GUI
python -m valscanner.cli /path     # CLI
```

Output files (`*.db`, `*.csv`, `*.json`) are gitignored.

### Building native apps

```bash
# macOS (.app bundle, optionally .dmg)
bash scripts/build_app.sh
bash scripts/build_app.sh --dmg

# Linux (standalone directory + .tar.gz)
bash scripts/build_app.sh

# Windows (.exe via PyInstaller, optionally Inno Setup installer)
.\scripts\build_app.ps1
.\scripts\build_app.ps1 -Installer
```

### Bumping the version

```bash
python scripts/bump_version.py 0.2.0
```

Updates `pyproject.toml`, `valscanner/__init__.py`, `valscanner.spec`, `build_app.sh`, `build_app.ps1`, and `assets/windows_version_info.txt` in one pass.

---

## License

MIT — Copyright (c) 2026 Abdalrahman Valabji

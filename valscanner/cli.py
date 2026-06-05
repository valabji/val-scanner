#!/usr/bin/env python3
from __future__ import annotations
"""
ValScanner CLI — scan a directory and build a searchable file database.

Usage:
    valscanner /path/to/scan [options]
    valscanner --list-scans --db my.db
    valscanner --delete-scan 3 --db my.db
"""

import logging
import subprocess
import sys
import time
import argparse
from pathlib import Path

from .core.app_settings import active_url, cli_defaults, mask_url, settings_path
from .core.bootstrap import ensure_schema
from .core.logging_config import setup_logging
from .core.metadata import PIL_AVAILABLE, MUTAGEN_AVAILABLE, PYPDF_AVAILABLE, FFMPEG_AVAILABLE
from .core.scanner import scan, count_files, ALL_PHASES, PHASE_ENUMERATE
from .core.export import export_csv, export_json
from .core.db import search_db, print_summary, print_db_status, list_scans, delete_scan, remap_scan, repo_for
from .core.schema import human_size
from .core.transfer import transfer_db
from .core.similarity import find_similar_folders
from ._telemetry import init_sentry

# Optional rich output — graceful fallback to plain print when not installed
try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
    _console = _RichConsole(highlight=False)
    _HAS_RICH = True
except ImportError:
    _console = None   # type: ignore[assignment]
    _HAS_RICH = False


def _rprint(markup: str, plain: str | None = None) -> None:
    """Print *markup* via rich if available, else fall back to *plain* (or *markup*)."""
    if _HAS_RICH:
        _console.print(markup)
    else:
        print(plain if plain is not None else markup)


def _export_stem(db_arg: str | None) -> str:
    """Filename stem for --export-csv / --export-json outputs.

    A SQLAlchemy URL (e.g. postgresql://user:pw@host/db) must never reach the
    filename — it would embed credentials. Only treat the arg as a path stem
    when it looks like a plain filesystem path.
    """
    if not db_arg:
        return "scan"
    if "://" in db_arg:
        return "scan"
    stem = Path(db_arg).stem
    return stem or "scan"


def _make_scan_progress_cb(verbose: bool, total: int, show_progress: bool = True):
    """Return an on_progress callback for scan(), or None if not applicable.

    When *verbose* is True the scanner pre-clears the bar line before each
    file print, so both can coexist on a TTY without garbling output.
    On a non-TTY there is no bar regardless of verbose.
    """
    if not show_progress or not sys.stdout.isatty():
        return None

    import time as _time
    BAR_W  = 25
    start  = _time.time()
    _last  = [0.0]  # last print time — throttle to 10 Hz

    def _fmt_eta(secs: float) -> str:
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        m, s = divmod(secs, 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"

    def _cb(event: dict) -> None:
        now = _time.time()
        if event.get("done"):
            print("\r" + " " * 79 + "\r", end="", flush=True)
            return
        if now - _last[0] < 0.1:
            return
        _last[0] = now

        scanned = event.get("scanned", 0)
        skipped = event.get("skipped", 0)
        done    = scanned + skipped  # Total files processed (new + duplicates)
        elapsed = max(now - start, 0.001)
        rate    = done / elapsed

        if total > 0:
            pct    = done / total
            filled = int(BAR_W * pct)
            bar    = "=" * filled + (">" if filled < BAR_W else "") + " " * (BAR_W - filled - (1 if filled < BAR_W else 0))
            remaining = total - done
            eta    = _fmt_eta(remaining / rate) if rate > 0 else "?"

            # Show distinction between skipped (already indexed) and newly scanned files
            if skipped > 0:
                line   = (f"\r  [{bar}] {pct*100:5.1f}%  {scanned:>4,}↻{skipped//1000}k  {rate:,.0f}/s  {eta}")
            else:
                line   = (f"\r  [{bar}] {done:>6,}/{total:,}  "
                          f"{pct*100:4.1f}%  {rate:,.0f} f/s  ETA {eta}")
        else:
            line   = f"\r  {done:>8,} files  {rate:,.0f} f/s"

        print(line[:79], end="", flush=True)

    return _cb


def _make_transfer_progress_cb(show_progress: bool = True):
    """Return (on_progress, on_stage_progress) callbacks for transfer_db().

    The progress-bar callback throttles to 10 Hz, redraws in place, and the
    stage-summary callback clears any active bar before printing.
    """
    if not show_progress:
        def _plain(msg: str) -> None:
            print(msg)
        return _plain, None

    import time as _time
    import shutil as _shutil
    BAR_W = 25
    state = {"stage": None, "start": 0.0, "last": 0.0, "active": False}

    def _cols() -> int:
        try:
            return max(40, _shutil.get_terminal_size((100, 24)).columns - 1)
        except OSError:
            return 99

    def _fmt_eta(secs: float) -> str:
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        m, s = divmod(secs, 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"

    def _clear() -> None:
        if state["active"]:
            print("\r" + " " * _cols() + "\r", end="", flush=True)
            state["active"] = False

    def on_progress(msg: str) -> None:
        _clear()
        print(msg)

    def on_stage(stage: str, done: int, total: int) -> None:
        now = _time.time()
        if stage != state["stage"]:
            state["stage"] = stage
            state["start"] = now
            state["last"] = 0.0
        # Throttle to 10 Hz, but always paint the final frame.
        if now - state["last"] < 0.1 and done < total:
            return
        state["last"] = now

        if total <= 0:
            return

        elapsed = max(now - state["start"], 0.001)
        rate    = done / elapsed
        pct     = done / total
        filled  = int(BAR_W * pct)
        bar     = "=" * filled + (">" if filled < BAR_W else "") + " " * (BAR_W - filled - (1 if filled < BAR_W else 0))
        remaining = total - done
        eta     = _fmt_eta(remaining / rate) if rate > 0 else "?"
        line    = (f"\r   {stage:<10s} [{bar}] {done:>7,}/{total:<7,}  "
                   f"{pct*100:4.1f}%  {rate:,.0f}/s  ETA {eta}")
        print(line[:_cols()], end="", flush=True)
        state["active"] = True

    return on_progress, on_stage


def _make_analysis_progress_cb(show_progress: bool = True):
    """Return an on_progress callback for find_similar_folders()."""
    if not show_progress:
        return None

    import time as _time
    BAR_W  = 25
    start  = _time.time()
    _last  = [0.0]  # last print time — throttle to 10 Hz

    def _fmt_eta(secs: float) -> str:
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        m, s = divmod(secs, 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"

    def _cb(done: int, total: int) -> None:
        now = _time.time()
        if now - _last[0] < 0.1:
            return
        _last[0] = now

        if total <= 0:
            return

        elapsed = max(now - start, 0.001)
        rate    = done / elapsed

        pct    = done / total
        filled = int(BAR_W * pct)
        bar    = "=" * filled + (">" if filled < BAR_W else "") + " " * (BAR_W - filled - (1 if filled < BAR_W else 0))
        remaining = total - done
        eta    = _fmt_eta(remaining / rate) if rate > 0 else "?"
        line   = (f"\r   [{bar}] {done:>6,}/{total:,}  "
                  f"{pct*100:4.1f}%  {rate:,.0f} p/s  ETA {eta}")

        print(line[:79], end="", flush=True)

    return _cb


def _run_analysis(url: str, args, scan_id: int | None) -> None:
    scan_ids = None
    if args.analysis_scan_id is not None:
        scan_ids = [args.analysis_scan_id]
    elif scan_id is not None:
        scan_ids = [scan_id]

    filters = {
        "skip_hidden_files": args.skip_hidden_files,
        "skip_hidden_dirs":  args.skip_hidden_dirs,
        "skip_system":       args.skip_system,
        "skip_caches":       args.skip_caches,
        "skip_vcs":          args.skip_vcs,
        "skip_binaries":     args.skip_binaries,
        "skip_temp":         args.skip_temp,
        "skip_logs":         args.skip_logs,
    }

    print(f"\n🔍 Running similarity analysis "
          f"(min-files={args.min_files}, threshold={args.threshold:.2f})…")

    pairs = find_similar_folders(
        url,
        min_files=args.min_files,
        threshold=args.threshold,
        max_results=args.analysis_results,
        scan_ids=scan_ids,
        filters=filters,
        progress_cb=_make_analysis_progress_cb(show_progress=not args.no_progress_bar),
    )
    if not args.no_progress_bar:
        print("\r" + " " * 79 + "\r", end="", flush=True)  # clear progress bar

    if not pairs:
        _rprint("   [dim]No similar folder pairs found.[/dim]\n",
                "   No similar folder pairs found.\n")
        return

    if _HAS_RICH:
        tbl = _RichTable(show_header=True, header_style="bold", box=None,
                         padding=(0, 1))
        tbl.add_column("Score", style="cyan", justify="right", width=6)
        tbl.add_column("Folder A", no_wrap=False)
        tbl.add_column("Folder B", no_wrap=False)
        for pair in pairs:
            tbl.add_row(f"{pair['score']:.2f}", pair["folder_a"], pair["folder_b"])
            for child in pair.get("children", []):
                tbl.add_row(f"{child['score']:.2f}",
                            f"  ↳ {child['folder_a']}", child["folder_b"])
        print()
        _console.print(tbl)
        _rprint(f"\n   [bold]{len(pairs)}[/bold] pair(s) found.\n",
                f"\n   {len(pairs)} pair(s) found.\n")
    else:
        print(f"\n   {'Score':>5}  {'Folder A':<45}  Folder B")
        print(f"   {'─'*5}  {'─'*45}  {'─'*45}")
        for pair in pairs:
            a = pair["folder_a"]
            b = pair["folder_b"]
            score = pair["score"]
            print(f"   {score:>5.2f}  {a:<45}  {b}")
            for child in pair.get("children", []):
                ca = child["folder_a"]
                cb = child["folder_b"]
                cs = child["score"]
                print(f"   {cs:>5.2f}    ↳ {ca:<43}  {cb}")
        print(f"\n   {len(pairs)} pair(s) found.\n")


def main() -> None:
    init_sentry("cli")
    _defs = cli_defaults()
    parser = argparse.ArgumentParser(
        description="Scan a directory and build a searchable file database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path",           nargs="?", help="Root directory to scan")
    parser.add_argument("--db",           default=None,
                        help="SQLite file path or full SQLAlchemy URL "
                             "(default: configured database)")
    parser.add_argument("--label",        metavar="NAME", default="",
                        help="Human-readable label for this scan")
    parser.add_argument("--export-csv",   action="store_true", help="Export results to CSV")
    parser.add_argument("--export-json",  action="store_true", help="Export results to JSON")
    parser.add_argument("--no-hash",      action="store_true", default=_defs["no_hash"],
                        help="Skip SHA-256 hashing")
    parser.add_argument("--resume",       action="store_true",
                        help="Resume an interrupted scan of the same path")
    parser.add_argument("--phases",       metavar="LIST", default=None,
                        help="Comma-separated subset of: enumerate, metadata, "
                             "thumbnails, hash, samples. Default: all five. "
                             "Use with --scan-id to re-enter an existing scan "
                             "for additional phases.")
    parser.add_argument("--scan-id",      type=int, default=None, metavar="N",
                        help="Target an existing scan for enrichment phases "
                             "(path argument becomes optional when set, as "
                             "long as 'enumerate' is not in --phases).")
    parser.add_argument("--scan-status",  action="store_true",
                        help="Print per-phase eligible/done counts for "
                             "--scan-id and exit.")
    parser.add_argument("--by-ext",       action="store_true",
                        help="With --scan-status, also break each phase down "
                             "by file extension (sorted by missing-count). "
                             "Useful for spotting misclassified extensions.")
    parser.add_argument("--by-ext-limit", type=int, default=15, metavar="N",
                        help="Max extensions to list per phase with --by-ext "
                             "(default: 15; use 0 for unlimited).")
    parser.add_argument("--verbose",      action="store_true", default=_defs["verbose"],
                        help="Print each file as indexed")
    parser.add_argument("--no-progress-bar", action="store_true", default=_defs["no_progress_bar"],
                        help="Disable progress bar output")
    parser.add_argument("--search",       metavar="TERM",
                        help="Full-text search the database and exit "
                             "(combine with --scan-id, --category, --limit)")
    parser.add_argument("--category",     metavar="CAT",
                        help="With --search: restrict to this category")
    parser.add_argument("--limit",        type=int, default=50, metavar="N",
                        help="With --search: max rows to print (default: 50)")
    parser.add_argument("--db-status",     action="store_true",
                        help="Show DB size, table counts, per-scan breakdown, and orphan entries")
    parser.add_argument("--list-scans",    action="store_true", help="List all scans in the database")
    parser.add_argument("--delete-scan",   type=int, metavar="ID", help="Delete a scan by ID")
    parser.add_argument("--remap-scan",    type=int, metavar="ID",
                        help="Remap a scan's root folder to a new location (use with --new-root)")
    parser.add_argument("--new-root",      metavar="PATH",
                        help="New root path for --remap-scan")
    parser.add_argument("--configure",       action="store_true",
                        help="Run the interactive configuration wizard and exit")
    parser.add_argument("--open-settings",   action="store_true",
                        help="Open settings.json in the system default editor and exit")
    parser.add_argument("--dump-to-sqlite",  metavar="FILE",
                        help="Export the connected database to a SQLite file and exit")
    parser.add_argument("--dump-scan-ids",   metavar="IDS",
                        help="Comma-separated scan IDs to include in --dump-to-sqlite "
                             "(e.g. 1,3,5); omit to dump all scans")
    parser.add_argument("--load-from-sqlite", metavar="FILE",
                        help="Import from a SQLite file into the connected database and exit")
    parser.add_argument("--include-analysis",    action="store_true",
                        help="Also transfer analysis runs (default: skipped)")
    parser.add_argument("--include-cache",       action="store_true",
                        help="Also transfer GUI cache entries (default: skipped)")
    parser.add_argument("--no-dump-thumbnails",  action="store_true",
                        help="Skip thumbnail blobs when dumping/loading (default: included)")
    parser.add_argument("--no-dump-samples",     action="store_true",
                        help="Skip media sample blobs when dumping/loading (default: included)")
    parser.add_argument("--zip-blobs",           nargs="?", const=True, metavar="FILE",
                        help="Dump: write blobs to FILE (default: <db>.zip) instead of SQLite. "
                             "Load: restore blobs from FILE (default: <db>.zip)")

    thumb = parser.add_argument_group("thumbnails (requires Pillow, on by default)")
    thumb.add_argument("--no-thumbnails",  action="store_true", default=_defs["no_thumbnails"],
                       help="Skip thumbnail generation")
    thumb.add_argument("--thumb-size",    type=int, default=_defs["thumb_size"], metavar="PX",
                       help="Thumbnail max dimension in pixels (default: 128)")
    thumb.add_argument("--thumb-quality", type=int, default=_defs["thumb_quality"], metavar="PCT",
                       help="Thumbnail JPEG quality 40-95 (default: 75)")

    media = parser.add_argument_group("media samples (requires ffmpeg, on by default)")
    media.add_argument("--no-samples",      action="store_true", default=_defs["no_samples"],
                       help="Skip audio/video sample generation")
    media.add_argument("--sample-duration", type=int, default=_defs["sample_duration"], metavar="SEC",
                       help="Media sample duration in seconds (default: 5)")

    skip = parser.add_argument_group("skip during scan (all off by default)")
    skip.add_argument("--skip-hidden-dirs",  action="store_true", default=_defs["skip_hidden_dirs"],
                      help="Skip hidden folders (names starting with .)")
    skip.add_argument("--skip-vcs",          action="store_true", default=_defs["skip_vcs"],
                      help="Skip version-control dirs (.git, .svn, .hg, …)")
    skip.add_argument("--skip-system",       action="store_true", default=_defs["skip_system"],
                      help="Skip OS system dirs (Windows, Library, /proc, …)")
    skip.add_argument("--skip-caches",       action="store_true", default=_defs["skip_caches"],
                      help="Skip cache/build dirs (node_modules, __pycache__, venv, …)")
    skip.add_argument("--skip-hidden-files", action="store_true", default=_defs["skip_hidden_files"],
                      help="Skip hidden files (names starting with .)")
    skip.add_argument("--skip-binaries",     action="store_true", default=_defs["skip_binaries"],
                      help="Skip binary/compiled files (.exe, .dll, .so, .pyc, …)")
    skip.add_argument("--skip-temp",         action="store_true", default=_defs["skip_temp"],
                      help="Skip temp/backup files (.tmp, .bak, .swp, .DS_Store, …)")
    skip.add_argument("--skip-logs",         action="store_true", default=_defs["skip_logs"],
                      help="Skip log files (.log)")
    skip.add_argument("--file-timeout",      type=int, default=_defs["file_timeout"], metavar="SEC",
                      help="Maximum time to wait per file in seconds (default: 120)")
    skip.add_argument("--exclude",           metavar="GLOB", action="append", default=[],
                      help="Skip files whose path (relative to root) matches GLOB "
                           "(repeatable; e.g. --exclude '*.pyc' --exclude '__pycache__/*')")

    perf = parser.add_argument_group("performance")
    perf.add_argument("--workers",      type=int, default=_defs["workers"], metavar="N",
                      help="Parallel file-processing threads (default: 4; 1 = sequential)")
    perf.add_argument("--no-precount",  action="store_true", default=_defs["no_precount"],
                      help="Skip the pre-scan file count; progress shows a spinner "
                           "with a running tally instead of a percentage bar")

    analysis = parser.add_argument_group("similarity analysis")
    analysis.add_argument("--analyze",          action="store_true",
                          help="Run folder-similarity analysis after scanning "
                               "(or standalone with --db, no path required)")
    analysis.add_argument("--min-files",        type=int, default=_defs["min_files"], metavar="N",
                          help="Minimum files per folder for analysis (default: 3)")
    analysis.add_argument("--threshold",        type=float, default=_defs["threshold"], metavar="F",
                          help="Minimum similarity score 0–1 (default: 0.40)")
    analysis.add_argument("--analysis-results", type=int, default=_defs["analysis_results"], metavar="N",
                          help="Maximum number of folder pairs to report (default: 200)")
    analysis.add_argument("--analysis-scan-id", type=int, default=None, metavar="ID",
                          help="Restrict analysis to a specific scan ID")

    logging_group = parser.add_argument_group("logging")
    logging_group.add_argument("--log-file",    metavar="PATH", default=None,
                               help="Write logs to file (default: no file logging)")
    logging_group.add_argument("--log-level",   metavar="LEVEL", default=_defs["log_level"],
                               choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                               help="Log level (default: INFO)")
    logging_group.add_argument("--log-max-size", type=int, default=_defs["log_max_size"], metavar="BYTES",
                               help="Max log file size before rotation in bytes (default: 10485760 = 10MB)")
    logging_group.add_argument("--log-backup-count", type=int, default=_defs["log_backup_count"], metavar="N",
                               help="Number of backup log files to keep (default: 5)")
    logging_group.add_argument("--log-no-console", action="store_true", default=_defs["log_no_console"],
                               help="Disable console output, log to file only")

    args = parser.parse_args()

    # Configure logging early
    setup_logging(
        log_file=args.log_file,
        log_level=args.log_level,
        log_max_size=args.log_max_size,
        log_backup_count=args.log_backup_count,
        log_no_console=args.log_no_console,
    )

    if args.configure:
        from .config_wizard import run_wizard
        sys.exit(run_wizard())

    if args.open_settings:
        sf = settings_path()
        print(f"Settings: {sf}")
        if sys.platform == "darwin":
            subprocess.run(["open", str(sf)])
        elif sys.platform == "win32":
            subprocess.run(["start", "", str(sf)], shell=True)
        else:
            subprocess.run(["xdg-open", str(sf)])
        sys.exit(0)

    url = active_url(args.db)
    ensure_schema(url)

    if args.db_status:
        print_db_status(url)
        sys.exit(0)

    if args.list_scans:
        scans = list_scans(url)
        if not scans:
            print("No scans in database.")
        for s in scans:
            print(f"  [{s['id']:3d}]  {s['label'] or s['root']:40s}  "
                  f"{s['file_count']:>8,} files  {s['total_human']:>10s}  {s['scanned_at']}")
        sys.exit(0)

    if args.search:
        search_db(
            url, args.search,
            scan_id=args.scan_id,
            category=args.category,
            limit=args.limit,
        )
        sys.exit(0)

    if args.delete_scan is not None:
        delete_scan(url, args.delete_scan)
        print(f"✓ Scan {args.delete_scan} deleted.")
        sys.exit(0)

    if args.remap_scan is not None:
        if not args.new_root:
            parser.error("--remap-scan requires --new-root PATH")
        new_root = str(Path(args.new_root).expanduser())
        if not Path(new_root).exists():
            print(f"⚠  New root {new_root} does not exist on disk — proceeding anyway.")
        summary = remap_scan(url, args.remap_scan, new_root)
        if summary["files_updated"] == 0 and summary["folders_updated"] == 0 \
           and not summary["files_skipped"] and not summary["folders_skipped"]:
            print(f"✓ Scan {args.remap_scan}: root already {summary['new_root']} — no changes.")
        else:
            print(f"✓ Scan {args.remap_scan} remapped:")
            print(f"    {summary['old_root']}")
            print(f"  → {summary['new_root']}")
            print(f"    {summary['files_updated']:,} files, "
                  f"{summary['folders_updated']:,} folders updated.")
            n_skip = len(summary["files_skipped"]) + len(summary["folders_skipped"])
            if n_skip:
                print(f"  ⚠ {n_skip} row(s) skipped (path not under old root).")
        sys.exit(0)

    if args.dump_to_sqlite:
        dst_path = Path(args.dump_to_sqlite).expanduser().resolve()
        dst_url  = f"sqlite:///{dst_path}"

        dump_scan_ids: list[int] | None = None
        if args.dump_scan_ids:
            try:
                dump_scan_ids = [int(x.strip()) for x in args.dump_scan_ids.split(",") if x.strip()]
            except ValueError:
                parser.error("--dump-scan-ids must be a comma-separated list of integers, e.g. 1,3,5")
        elif args.scan_id is not None:
            dump_scan_ids = [args.scan_id]

        if args.zip_blobs is None:
            write_zip = None
        elif args.zip_blobs is True:
            write_zip = dst_path.with_suffix(".zip")
        else:
            write_zip = Path(args.zip_blobs).expanduser().resolve()
        print(f"\n📦 Exporting  {mask_url(url)}")
        if dump_scan_ids:
            ids_str = ", ".join(str(i) for i in dump_scan_ids)
            print(f"   Scans:    [{ids_str}]")
        print(f"         →  {dst_path}")
        if write_zip:
            print(f"   Blobs  →  {write_zip}")
        print()
        on_prog, on_stage = _make_transfer_progress_cb(show_progress=not args.no_progress_bar)
        stats = transfer_db(url, dst_url, on_progress=on_prog,
                            on_stage_progress=on_stage,
                            include_analysis=args.include_analysis,
                            include_cache=args.include_cache,
                            include_thumbnails=not (args.no_dump_thumbnails or args.zip_blobs is not None),
                            include_samples=not (args.no_dump_samples or args.zip_blobs is not None),
                            scan_ids=dump_scan_ids,
                            write_blobs_zip=write_zip)
        print(f"\n✅ Done — {stats['scans']} scans, {stats['files']:,} files")
        sys.exit(0)

    if args.load_from_sqlite:
        src_path = Path(args.load_from_sqlite).expanduser().resolve()
        if not src_path.exists():
            print(f"Error: file not found: {src_path}")
            sys.exit(1)
        src_url = f"sqlite:///{src_path}"
        if args.zip_blobs is None:
            read_zip = None
        elif args.zip_blobs is True:
            read_zip = src_path.with_suffix(".zip")
        else:
            read_zip = Path(args.zip_blobs).expanduser().resolve()
        print(f"\n📥 Importing  {src_path}")
        if read_zip:
            print(f"   Blobs  ←  {read_zip}")
        print(f"         →  {mask_url(url)}\n")
        on_prog, on_stage = _make_transfer_progress_cb(show_progress=not args.no_progress_bar)
        stats = transfer_db(src_url, url, on_progress=on_prog,
                            on_stage_progress=on_stage,
                            include_analysis=args.include_analysis,
                            include_cache=args.include_cache,
                            include_thumbnails=not (args.no_dump_thumbnails or args.zip_blobs is not None),
                            include_samples=not (args.no_dump_samples or args.zip_blobs is not None),
                            read_blobs_zip=read_zip)
        print(f"\n✅ Done — {stats['scans']} scans, {stats['files']:,} files")
        sys.exit(0)

    if args.scan_status:
        if args.scan_id is None:
            parser.error("--scan-status requires --scan-id N")
        repo = repo_for(url)
        scan_info = repo.get_scan(args.scan_id)
        if scan_info is None:
            print(f"Error: scan #{args.scan_id} not found.")
            sys.exit(1)
        status = repo.phase_status(args.scan_id)
        label = scan_info.get("label") or scan_info.get("root") or ""
        print(f"\nScan #{args.scan_id}  {label}")
        print(f"  Root: {scan_info.get('root')}")
        print(f"  Status: {scan_info.get('status')}\n")
        print(f"  {'phase':<12} {'done':>10} / {'eligible':<10}  {'%':>6}")
        print(f"  {'-'*12} {'-'*10}   {'-'*10}  {'-'*6}")
        for phase in ALL_PHASES:
            row = status.get(phase, {"done": 0, "eligible": 0})
            done = row["done"]
            elig = row["eligible"]
            pct = (100.0 * done / elig) if elig else 100.0
            print(f"  {phase:<12} {done:>10,} / {elig:<10,}  {pct:>5.1f}%")
        print()

        if args.by_ext:
            by_ext = repo.phase_status_by_extension(args.scan_id)
            limit = args.by_ext_limit if args.by_ext_limit > 0 else None
            for phase in ALL_PHASES:
                rows = [r for r in by_ext.get(phase, []) if r["eligible"] > 0]
                if not rows:
                    continue
                print(f"  {phase} by extension:")
                shown = rows if limit is None else rows[:limit]
                for r in shown:
                    missing = r["eligible"] - r["done"]
                    marker = f"  ({missing:,} missing)" if missing else ""
                    print(f"    {r['ext']:<12} "
                          f"{r['done']:>8,} / {r['eligible']:<8,}{marker}")
                if limit is not None and len(rows) > limit:
                    print(f"    … +{len(rows) - limit} more (raise --by-ext-limit to see)")
                print()
        sys.exit(0)

    if args.analyze and not args.path:
        _run_analysis(url, args, scan_id=None)
        sys.exit(0)

    # Parse --phases into a tuple (or None for default). Validate names early
    # so a typo doesn't waste a precount before failing.
    phases_arg: tuple | None = None
    if args.phases is not None:
        requested = [p.strip().lower() for p in args.phases.split(",") if p.strip()]
        unknown = [p for p in requested if p not in ALL_PHASES]
        if unknown:
            parser.error(f"--phases: unknown phase(s) {unknown} "
                         f"(valid: {list(ALL_PHASES)})")
        phases_arg = tuple(p for p in ALL_PHASES if p in set(requested))

    enrichment_only = (
        args.scan_id is not None
        and phases_arg is not None
        and PHASE_ENUMERATE not in phases_arg
    )

    if not args.path and not enrichment_only:
        parser.error("path is required unless using --db-status, --list-scans, --delete-scan, "
                     "--search, --configure, --open-settings, --dump-to-sqlite, "
                     "--load-from-sqlite, --scan-status, --analyze, or "
                     "--scan-id with --phases that exclude 'enumerate'")

    if args.path:
        root = Path(args.path).expanduser().resolve()
        if not root.exists():
            print(f"Error: path does not exist: {root}")
            sys.exit(1)
    else:
        # Enrichment-only run: borrow root from the existing scan for messaging.
        repo = repo_for(url)
        existing = repo.get_scan(args.scan_id)
        if existing is None:
            print(f"Error: scan #{args.scan_id} not found.")
            sys.exit(1)
        root = Path(existing["root"])

    store_thumbnails = not args.no_thumbnails
    store_samples    = not args.no_samples

    _rprint(f"\n[bold]🔎 Scanning:[/bold] {root}", f"\n🔎 Scanning: {root}")
    if args.verbose:
        _rprint(f"   [dim]Database:[/dim] {mask_url(url)}",
                f"   Database: {mask_url(url)}")
    if args.label:
        _rprint(f"   [dim]Label:[/dim]    {args.label}",
                f"   Label:    {args.label}")
    if store_thumbnails and not PIL_AVAILABLE:
        _rprint("   [yellow]⚠[/yellow]  Pillow not installed — thumbnail generation skipped",
                "   ⚠  Pillow not installed — thumbnail generation skipped")
    if store_samples and not FFMPEG_AVAILABLE:
        _rprint("   [yellow]⚠[/yellow]  ffmpeg not found — media sample generation skipped",
                "   ⚠  ffmpeg not found — media sample generation skipped")
    if not PIL_AVAILABLE:
        _rprint("   [yellow]⚠[/yellow]  Pillow not installed — image EXIF metadata skipped",
                "   ⚠  Pillow not installed — image EXIF metadata skipped")
    if not MUTAGEN_AVAILABLE:
        _rprint("   [yellow]⚠[/yellow]  mutagen not installed — audio metadata skipped",
                "   ⚠  mutagen not installed — audio metadata skipped")
    if not PYPDF_AVAILABLE:
        _rprint("   [yellow]⚠[/yellow]  pypdf not installed — PDF metadata skipped",
                "   ⚠  pypdf not installed — PDF metadata skipped")
    print()

    skip_kw = dict(
        skip_hidden_dirs=args.skip_hidden_dirs,
        skip_vcs=args.skip_vcs,
        skip_system=args.skip_system,
        skip_caches=args.skip_caches,
        skip_hidden_files=args.skip_hidden_files,
        skip_binaries=args.skip_binaries,
        skip_temp=args.skip_temp,
        skip_logs=args.skip_logs,
    )

    total_files = 0
    remaining_files = 0
    # Skip the pre-scan count when --no-precount is set OR when --verbose is
    # active (verbose disables the progress bar anyway, so the count is unused).
    _do_precount = (
        sys.stdout.isatty()
        and not args.no_precount
        and not args.verbose
        and not enrichment_only
    )
    if _do_precount:
        print("   Counting files…", end="", flush=True)
        total_files = count_files(root, **skip_kw,
                                  exclude_patterns=args.exclude or None)
        remaining_files = total_files

        # If resuming, show how many files are already indexed
        if args.resume:
            repo = repo_for(url)
            interrupted_scan = repo.find_interrupted_scan(str(root))
            if interrupted_scan:
                scan_info = repo.get_scan(interrupted_scan)
                already_indexed = scan_info.get("file_count", 0) if scan_info else 0
                remaining_files = max(0, total_files - already_indexed)
                print(f"\r   {total_files:,} total files, {already_indexed:,} already indexed, "
                      f"{remaining_files:,} remaining\n", flush=True)
            else:
                print(f"\r   {total_files:,} files to index\n", flush=True)
        else:
            print(f"\r   {total_files:,} files to index\n", flush=True)

    t0 = time.time()
    t_pre_scan = time.time()
    try:
        stats = scan(
            root, url,
            compute_hash=not args.no_hash,
            verbose=args.verbose,
            label=args.label,
            resume=args.resume,
            store_thumbnails=store_thumbnails,
            thumb_size=args.thumb_size,
            thumb_quality=args.thumb_quality,
            store_samples=store_samples,
            sample_duration=args.sample_duration,
            file_timeout=args.file_timeout,
            workers=args.workers,
            exclude_patterns=args.exclude or None,
            on_progress=_make_scan_progress_cb(args.verbose, total_files, show_progress=not args.no_progress_bar),
            phases=phases_arg,
            scan_id=args.scan_id,
            **skip_kw,
        )
    except KeyboardInterrupt:
        elapsed = time.time() - t0
        # Find the running scan and update its totals before exiting
        repo = repo_for(url)
        running_scan_id = repo.find_interrupted_scan(str(root))
        if running_scan_id:
            # Count files already indexed for this scan
            files = repo.iter_files_for_export(scan_id=running_scan_id)
            file_count = sum(1 for _ in files)
            # Recalculate totals from database
            scan_files = repo.list_files(scan_id=running_scan_id, page_size=10000)
            total_bytes = sum(f.get("size_bytes", 0) for f in scan_files)
            repo.update_scan_totals(running_scan_id, file_count, total_bytes, human_size(total_bytes))
        print(f"\n⏸️  Scan interrupted after {elapsed:.1f}s")
        print(f"   Run with --resume to continue from where it stopped.\n")
        sys.exit(0)

    elapsed = time.time() - t0

    timed_out = stats.get("timed_out", 0)
    timed_out_str = f", {timed_out:,} timed out" if timed_out > 0 else ""

    _done_plain = (f"\n✅ Done in {elapsed:.1f}s — "
                   f"scan #{stats['scan_id']}, "
                   f"{stats['scanned']:,} indexed, "
                   f"{stats['errors']:,} errors, "
                   f"{stats['skipped']:,} skipped{timed_out_str}")
    _rprint(
        f"\n[bold green]✅ Done[/bold green] in [bold]{elapsed:.1f}s[/bold] — "
        f"scan [cyan]#{stats['scan_id']}[/cyan], "
        f"[bold]{stats['scanned']:,}[/bold] indexed, "
        f"{stats['errors']:,} errors, "
        f"{stats['skipped']:,} skipped{timed_out_str}",
        _done_plain,
    )

    per_phase = stats.get("per_phase") or {}
    enrichment_phases = [p for p in per_phase
                        if p != PHASE_ENUMERATE and per_phase[p].get("seen", 0) > 0]
    if enrichment_phases:
        print()
        for phase in enrichment_phases:
            s = per_phase[phase]
            seen = s.get("seen", 0)
            processed = s.get("processed", 0)
            noop = s.get("noop", 0)
            errors = s.get("errors", 0)
            timed = s.get("timed_out", 0)
            skipped = s.get("skipped", 0)
            extras = []
            if noop:    extras.append(f"{noop:,} no output")
            if skipped: extras.append(f"{skipped:,} missing on disk")
            if timed:   extras.append(f"{timed:,} timed out")
            if errors:  extras.append(f"{errors:,} errors")
            tail = f"  ({', '.join(extras)})" if extras else ""
            print(f"   {phase:<11s} {processed:>5,}/{seen:<5,} written{tail}")

    if not enrichment_only:
        print_summary(url)

    db_stem = _export_stem(args.db)
    if args.export_csv:
        export_csv(url, f"{db_stem}.csv", scan_id=stats["scan_id"])
    if args.export_json:
        export_json(url, f"{db_stem}.json", scan_id=stats["scan_id"])

    if args.analyze:
        _run_analysis(url, args, scan_id=stats["scan_id"])

    print(f"  💡 Run with --search photos, --list-scans, or open the GUI:\n"
          f"     valscanner-gui\n")


if __name__ == "__main__":
    main()

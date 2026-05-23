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

from .core.app_settings import active_url, mask_url, settings_path
from .core.bootstrap import ensure_schema
from .core.metadata import PIL_AVAILABLE, MUTAGEN_AVAILABLE, PYPDF_AVAILABLE, FFMPEG_AVAILABLE
from .core.scanner import scan
from .core.export import export_csv, export_json
from .core.db import query_db, print_summary, list_scans, delete_scan
from .core.transfer import transfer_db


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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
    parser.add_argument("--no-hash",      action="store_true", help="Skip SHA-256 hashing")
    parser.add_argument("--resume",       action="store_true",
                        help="Resume an interrupted scan of the same path")
    parser.add_argument("--verbose",      action="store_true", help="Print each file as indexed")
    parser.add_argument("--query",        metavar="TERM", help="Query the database after scanning")
    parser.add_argument("--list-scans",    action="store_true", help="List all scans in the database")
    parser.add_argument("--delete-scan",   type=int, metavar="ID", help="Delete a scan by ID")
    parser.add_argument("--open-settings",   action="store_true",
                        help="Open settings.json in the system default editor and exit")
    parser.add_argument("--dump-to-sqlite",  metavar="FILE",
                        help="Export the connected database to a SQLite file and exit")
    parser.add_argument("--load-from-sqlite", metavar="FILE",
                        help="Import from a SQLite file into the connected database and exit")
    parser.add_argument("--include-analysis", action="store_true",
                        help="Also transfer analysis runs (default: skipped)")
    parser.add_argument("--include-cache",    action="store_true",
                        help="Also transfer GUI cache entries (default: skipped)")

    thumb = parser.add_argument_group("thumbnails (requires Pillow, on by default)")
    thumb.add_argument("--no-thumbnails",  action="store_true",
                       help="Skip thumbnail generation")
    thumb.add_argument("--thumb-size",    type=int, default=128, metavar="PX",
                       help="Thumbnail max dimension in pixels (default: 128)")
    thumb.add_argument("--thumb-quality", type=int, default=75,  metavar="PCT",
                       help="Thumbnail JPEG quality 40-95 (default: 75)")

    media = parser.add_argument_group("media samples (requires ffmpeg, on by default)")
    media.add_argument("--no-samples",      action="store_true",
                       help="Skip audio/video sample generation")
    media.add_argument("--sample-duration", type=int, default=5, metavar="SEC",
                       help="Media sample duration in seconds (default: 5)")

    skip = parser.add_argument_group("skip during scan (all off by default)")
    skip.add_argument("--skip-hidden-dirs",  action="store_true",
                      help="Skip hidden folders (names starting with .)")
    skip.add_argument("--skip-vcs",          action="store_true",
                      help="Skip version-control dirs (.git, .svn, .hg, …)")
    skip.add_argument("--skip-system",       action="store_true",
                      help="Skip OS system dirs (Windows, Library, /proc, …)")
    skip.add_argument("--skip-caches",       action="store_true",
                      help="Skip cache/build dirs (node_modules, __pycache__, venv, …)")
    skip.add_argument("--skip-hidden-files", action="store_true",
                      help="Skip hidden files (names starting with .)")
    skip.add_argument("--skip-binaries",     action="store_true",
                      help="Skip binary/compiled files (.exe, .dll, .so, .pyc, …)")
    skip.add_argument("--skip-temp",         action="store_true",
                      help="Skip temp/backup files (.tmp, .bak, .swp, .DS_Store, …)")
    skip.add_argument("--skip-logs",         action="store_true",
                      help="Skip log files (.log)")

    args = parser.parse_args()

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

    if args.list_scans:
        scans = list_scans(url)
        if not scans:
            print("No scans in database.")
        for s in scans:
            print(f"  [{s['id']:3d}]  {s['label'] or s['root']:40s}  "
                  f"{s['file_count']:>8,} files  {s['total_human']:>10s}  {s['scanned_at']}")
        sys.exit(0)

    if args.delete_scan is not None:
        delete_scan(url, args.delete_scan)
        print(f"✓ Scan {args.delete_scan} deleted.")
        sys.exit(0)

    if args.dump_to_sqlite:
        dst_path = Path(args.dump_to_sqlite).expanduser().resolve()
        dst_url  = f"sqlite:///{dst_path}"
        print(f"\n📦 Exporting  {mask_url(url)}")
        print(f"         →  {dst_path}\n")
        stats = transfer_db(url, dst_url, on_progress=print,
                            include_analysis=args.include_analysis,
                            include_cache=args.include_cache)
        print(f"\n✅ Done — {stats['scans']} scans, {stats['files']:,} files")
        sys.exit(0)

    if args.load_from_sqlite:
        src_path = Path(args.load_from_sqlite).expanduser().resolve()
        if not src_path.exists():
            print(f"Error: file not found: {src_path}")
            sys.exit(1)
        src_url = f"sqlite:///{src_path}"
        print(f"\n📥 Importing  {src_path}")
        print(f"         →  {mask_url(url)}\n")
        stats = transfer_db(src_url, url, on_progress=print,
                            include_analysis=args.include_analysis,
                            include_cache=args.include_cache)
        print(f"\n✅ Done — {stats['scans']} scans, {stats['files']:,} files")
        sys.exit(0)

    if not args.path:
        parser.error("path is required unless using --list-scans, --delete-scan, "
                     "--open-settings, --dump-to-sqlite, or --load-from-sqlite")

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"Error: path does not exist: {root}")
        sys.exit(1)

    store_thumbnails = not args.no_thumbnails
    store_samples    = not args.no_samples

    print(f"\n🔎 Scanning: {root}")
    if args.verbose:
        print(f"   Database: {mask_url(url)}")
    if args.label:
        print(f"   Label:    {args.label}")
    if store_thumbnails and not PIL_AVAILABLE:
        print("   ⚠  Pillow not installed — thumbnail generation skipped")
    if store_samples and not FFMPEG_AVAILABLE:
        print("   ⚠  ffmpeg not found — media sample generation skipped")
    if not PIL_AVAILABLE:
        print("   ⚠  Pillow not installed — image EXIF metadata skipped")
    if not MUTAGEN_AVAILABLE:
        print("   ⚠  mutagen not installed — audio metadata skipped")
    if not PYPDF_AVAILABLE:
        print("   ⚠  PyPDF2 not installed — PDF metadata skipped")
    print()

    t0    = time.time()
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
        skip_hidden_dirs=args.skip_hidden_dirs,
        skip_vcs=args.skip_vcs,
        skip_system=args.skip_system,
        skip_caches=args.skip_caches,
        skip_hidden_files=args.skip_hidden_files,
        skip_binaries=args.skip_binaries,
        skip_temp=args.skip_temp,
        skip_logs=args.skip_logs,
    )
    elapsed = time.time() - t0

    print(f"\n✅ Done in {elapsed:.1f}s — "
          f"scan #{stats['scan_id']}, "
          f"{stats['scanned']:,} indexed, "
          f"{stats['errors']:,} errors, "
          f"{stats['skipped']:,} skipped")

    print_summary(url)

    db_stem = _export_stem(args.db)
    if args.export_csv:
        export_csv(url, f"{db_stem}.csv", scan_id=stats["scan_id"])
    if args.export_json:
        export_json(url, f"{db_stem}.json", scan_id=stats["scan_id"])
    if args.query:
        query_db(url, args.query)

    print(f"  💡 Run with --query photos, --list-scans, or open the GUI:\n"
          f"     valscanner-gui\n")


if __name__ == "__main__":
    main()

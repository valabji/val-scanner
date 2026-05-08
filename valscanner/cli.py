#!/usr/bin/env python3
from __future__ import annotations
"""
ValScanner CLI — scan a directory and build a searchable file database.

Usage:
    valscanner /path/to/scan [options]
    valscanner --list-scans --db my.db
    valscanner --delete-scan 3 --db my.db
"""

import sys
import time
import argparse
from pathlib import Path

from .core.metadata import PIL_AVAILABLE, MUTAGEN_AVAILABLE, PYPDF_AVAILABLE
from .core.scanner import scan
from .core.export import export_csv, export_json
from .core.db import query_db, print_summary, list_scans, delete_scan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan a directory and build a searchable file database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path",           nargs="?", help="Root directory to scan")
    parser.add_argument("--db",           default="file_index.db",
                        help="SQLite database path (default: file_index.db)")
    parser.add_argument("--label",        metavar="NAME", default="",
                        help="Human-readable label for this scan")
    parser.add_argument("--export-csv",   action="store_true", help="Export results to CSV")
    parser.add_argument("--export-json",  action="store_true", help="Export results to JSON")
    parser.add_argument("--no-hash",      action="store_true", help="Skip SHA-256 hashing")
    parser.add_argument("--verbose",      action="store_true", help="Print each file as indexed")
    parser.add_argument("--query",        metavar="TERM", help="Query the database after scanning")
    parser.add_argument("--list-scans",   action="store_true", help="List all scans in the database")
    parser.add_argument("--delete-scan",  type=int, metavar="ID", help="Delete a scan by ID")
    args = parser.parse_args()

    if args.list_scans:
        scans = list_scans(args.db)
        if not scans:
            print("No scans in database.")
        for s in scans:
            print(f"  [{s['id']:3d}]  {s['label'] or s['root']:40s}  "
                  f"{s['file_count']:>8,} files  {s['total_human']:>10s}  {s['scanned_at']}")
        sys.exit(0)

    if args.delete_scan is not None:
        delete_scan(args.db, args.delete_scan)
        print(f"✓ Scan {args.delete_scan} deleted.")
        sys.exit(0)

    if not args.path:
        parser.error("path is required unless using --list-scans or --delete-scan")

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        print(f"Error: path does not exist: {root}")
        sys.exit(1)

    print(f"\n🔎 Scanning: {root}")
    print(f"   Database: {args.db}")
    if args.label:
        print(f"   Label:    {args.label}")
    if not PIL_AVAILABLE:
        print("   ⚠  Pillow not installed — image EXIF metadata skipped")
    if not MUTAGEN_AVAILABLE:
        print("   ⚠  mutagen not installed — audio metadata skipped")
    if not PYPDF_AVAILABLE:
        print("   ⚠  PyPDF2 not installed — PDF metadata skipped")
    print()

    t0      = time.time()
    stats   = scan(root, args.db, compute_hash=not args.no_hash,
                   verbose=args.verbose, label=args.label)
    elapsed = time.time() - t0

    print(f"\n✅ Done in {elapsed:.1f}s — "
          f"scan #{stats['scan_id']}, "
          f"{stats['scanned']:,} indexed, "
          f"{stats['errors']:,} errors, "
          f"{stats['skipped']:,} skipped")

    print_summary(args.db)

    if args.export_csv:
        export_csv(args.db, args.db.replace(".db", ".csv"), scan_id=stats["scan_id"])
    if args.export_json:
        export_json(args.db, args.db.replace(".db", ".json"), scan_id=stats["scan_id"])
    if args.query:
        query_db(args.db, args.query)

    print(f"  💡 Run with --query photos, --list-scans, or open the GUI:\n"
          f"     valscanner-gui\n")


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from valscanner.core.scanner import scan
from valscanner.core.export import export_csv, export_json


def test_export_csv_and_json():
    with tempfile.TemporaryDirectory() as scandir, tempfile.TemporaryDirectory() as dbdir:
        (Path(scandir) / "x.txt").write_text("hi")
        db = f"{dbdir}/e.db"
        result = scan(Path(scandir), db, compute_hash=False)

        csv_path = f"{dbdir}/out.csv"
        json_path = f"{dbdir}/out.json"
        export_csv(db, csv_path, scan_id=result["scan_id"])
        export_json(db, json_path, scan_id=result["scan_id"])

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1

        data = json.loads(Path(json_path).read_text())
        assert len(data) == 1


def test_scan_emits_progress_callback():
    """The on_progress arg replaces the os.walk monkey-patch."""
    with tempfile.TemporaryDirectory() as scandir, tempfile.TemporaryDirectory() as dbdir:
        for i in range(3):
            (Path(scandir) / f"f{i}.txt").write_text("x")
        events = []
        scan(Path(scandir), f"{dbdir}/p.db",
             compute_hash=False, on_progress=events.append)
        per_file = [e for e in events if "path" in e]
        assert len(per_file) == 3
        assert events[-1].get("done") is True

from __future__ import annotations

from pathlib import Path

from valscanner.core.scanner import scan
from valscanner.core.similarity import find_similar_folders


def test_similarity_finds_near_identical_folders(tmp_path: Path):
    scandir = tmp_path / "scan"
    scandir.mkdir()
    for sub in ("alpha", "beta"):
        d = scandir / sub
        d.mkdir()
        for name in ("a.txt", "b.pdf", "c.png"):
            (d / name).write_text("hello")

    db = str(tmp_path / "sim.db")
    scan(scandir, db, compute_hash=False)
    pairs = find_similar_folders(db, min_files=2, threshold=0.3)
    assert pairs, "similarity should find alpha vs beta"

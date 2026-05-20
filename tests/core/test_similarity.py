from __future__ import annotations

import tempfile
from pathlib import Path

from valscanner.core.scanner import scan
from valscanner.core.similarity import find_similar_folders


def test_similarity_finds_near_identical_folders():
    with tempfile.TemporaryDirectory() as scandir, tempfile.TemporaryDirectory() as dbdir:
        for sub in ("alpha", "beta"):
            d = Path(scandir, sub)
            d.mkdir()
            for name in ("a.txt", "b.pdf", "c.png"):
                (d / name).write_text("hello")

        db = f"{dbdir}/sim.db"
        scan(Path(scandir), db, compute_hash=False)
        pairs = find_similar_folders(db, min_files=2, threshold=0.3)
        assert pairs, "similarity should find alpha vs beta"

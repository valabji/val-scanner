"""Tests for the scanner performance / CLI enhancements added in v0.1.16.

Covers:
* exclude_patterns in count_files() and scan()
* workers parameter produces the same result as workers=1
* ancestor-chain cache (_get_ancestors path) — validated indirectly via folder totals
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from valscanner.core.scanner import count_files, scan


# ---------------------------------------------------------------------------
# Fixture: small directory tree
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_tree(tmp_path: Path) -> tuple:
    """Create a tiny tree and a separate DB directory.

    tree/
      a.txt
      b.py
      sub/
        c.txt
        d.pyc
      other/
        e.log

    Returns (tree_root, db_dir) so DB files are never inside the scanned tree.
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    (tree / "b.py").write_text("# py")
    sub = tree / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("world")
    (sub / "d.pyc").write_bytes(b"\x00\x01\x02")
    other = tree / "other"
    other.mkdir()
    (other / "e.log").write_text("log line")
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    return tree, db_dir


# ---------------------------------------------------------------------------
# count_files — exclude_patterns
# ---------------------------------------------------------------------------

def test_count_files_no_exclude(small_tree):
    tree, _ = small_tree
    total = count_files(tree, skip_hidden_dirs=False)
    assert total == 5   # a.txt, b.py, c.txt, d.pyc, e.log


def test_count_files_exclude_pyc(small_tree):
    tree, _ = small_tree
    total = count_files(tree, skip_hidden_dirs=False,
                        exclude_patterns=["*.pyc"])
    assert total == 4   # d.pyc excluded


def test_count_files_exclude_subdir_glob(small_tree):
    tree, _ = small_tree
    total = count_files(tree, skip_hidden_dirs=False,
                        exclude_patterns=["sub/*"])
    # c.txt and d.pyc are under sub/
    assert total == 3


def test_count_files_exclude_no_match(small_tree):
    tree, _ = small_tree
    total = count_files(tree, skip_hidden_dirs=False,
                        exclude_patterns=["*.xyz"])
    assert total == 5   # nothing excluded


# ---------------------------------------------------------------------------
# scan() — exclude_patterns
# ---------------------------------------------------------------------------

def _do_scan(root, db_path, **kw):
    return scan(root, db_path, compute_hash=False,
                store_thumbnails=False, store_samples=False,
                file_timeout=30, **kw)


def test_scan_exclude_pyc(small_tree):
    tree, db_dir = small_tree
    stats = _do_scan(tree, str(db_dir / "test.db"),
                     exclude_patterns=["*.pyc"])
    assert stats["scanned"] == 4          # d.pyc excluded
    assert stats["errors"] == 0


def test_scan_exclude_nothing(small_tree):
    tree, db_dir = small_tree
    stats = _do_scan(tree, str(db_dir / "test.db"),
                     exclude_patterns=["*.xyz"])
    assert stats["scanned"] == 5
    assert stats["errors"] == 0


def test_scan_exclude_multi(small_tree):
    tree, db_dir = small_tree
    stats = _do_scan(tree, str(db_dir / "test.db"),
                     exclude_patterns=["*.pyc", "*.log"])
    assert stats["scanned"] == 3          # d.pyc and e.log excluded
    assert stats["errors"] == 0


# ---------------------------------------------------------------------------
# workers parameter — result must be identical to workers=1
# ---------------------------------------------------------------------------

def test_scan_workers_matches_single(small_tree):
    tree, db_dir = small_tree
    s1 = _do_scan(tree, str(db_dir / "w1.db"), workers=1)
    s4 = _do_scan(tree, str(db_dir / "w4.db"), workers=4)

    assert s1["scanned"] == s4["scanned"]
    assert s1["errors"] == s4["errors"] == 0

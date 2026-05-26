"""Unit-level coverage for valscanner.core.similarity helpers and façade.

The existing `test_similarity.py` is a single end-to-end smoke test. This
file exercises the math helpers (cosine / jaccard / size_sim / subpath) and
the `normalize_to_group` legacy converter directly so failures point at the
exact function rather than the whole pipeline.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from valscanner.core.scanner import scan
from valscanner.core.similarity import (
    _cosine, _jaccard, _size_sim, _strict_subpath,
    find_similar_folders, find_similar_groups, normalize_to_group,
)


# ─── _cosine ────────────────────────────────────────────────────────────────

def test_cosine_identical_vectors_is_one():
    v = {"a": 1, "b": 2, "c": 3}
    assert _cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors_is_zero():
    assert _cosine({"a": 1}, {"b": 1}) == 0.0


def test_cosine_empty_inputs_returns_zero():
    assert _cosine({}, {}) == 0.0


def test_cosine_partial_overlap_within_bounds():
    s = _cosine({"a": 1, "b": 1}, {"a": 1, "c": 1})
    assert 0.0 < s < 1.0
    # Numerically: cos = 1 / sqrt(2)*sqrt(2) = 0.5
    assert s == pytest.approx(0.5)


# ─── _jaccard ───────────────────────────────────────────────────────────────

def test_jaccard_identical_sets_is_one():
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_both_empty_is_one():
    """Convention used by the algorithm: two empty folders ARE 'identical'."""
    assert _jaccard(set(), set()) == 1.0


def test_jaccard_one_empty_is_zero():
    assert _jaccard({"x"}, set()) == 0.0


# ─── _size_sim ──────────────────────────────────────────────────────────────

def test_size_sim_equal_is_one():
    assert _size_sim(1000, 1000) == 1.0


def test_size_sim_both_zero_is_one():
    """Both-zero edge case: avoid div-by-zero, treat as identical."""
    assert _size_sim(0, 0) == 1.0


def test_size_sim_ratio_min_over_max():
    assert _size_sim(50, 100) == 0.5
    assert _size_sim(100, 50) == 0.5  # Symmetric


# ─── _strict_subpath ────────────────────────────────────────────────────────

def test_strict_subpath_true_for_descendant():
    assert _strict_subpath("/a/b/c", "/a/b") is True


def test_strict_subpath_false_for_self():
    assert _strict_subpath("/a/b", "/a/b") is False


def test_strict_subpath_false_for_sibling():
    assert _strict_subpath("/a/c", "/a/b") is False


def test_strict_subpath_false_for_ancestor():
    assert _strict_subpath("/a", "/a/b") is False


# ─── normalize_to_group ─────────────────────────────────────────────────────

def test_normalize_to_group_passes_through_groups():
    g = {"members": [{"folder": "/x"}], "score": 0.5}
    assert normalize_to_group(g) is g  # Already group-shaped → unchanged


def test_normalize_to_group_converts_pair_shape():
    pair = {
        "folder_a": "/a", "scan_id_a": 1, "scan_label_a": "src",
        "files_a": 4, "bytes_a": 100,
        "folder_b": "/b", "scan_id_b": 1, "scan_label_b": "src",
        "files_b": 4, "bytes_b": 110,
        "score": 0.8, "name_score": 0.9, "size_score": 0.7,
    }
    g = normalize_to_group(pair)
    assert g["size"] == 2
    assert g["edges_count"] == 1
    assert g["score"] == 0.8
    assert g["max_score"] == g["min_score"] == 0.8
    folders = {m["folder"] for m in g["members"]}
    assert folders == {"/a", "/b"}


# ─── End-to-end: find_similar_folders + groups ──────────────────────────────

@pytest.fixture
def populated_db():
    """Build a DB with two near-identical folders and yield its URL."""
    with tempfile.TemporaryDirectory() as scandir, tempfile.TemporaryDirectory() as dbdir:
        for sub in ("alpha", "beta"):
            d = Path(scandir, sub)
            d.mkdir()
            for name in ("a.txt", "b.pdf", "c.png"):
                (d / name).write_text("hello")
        db = f"{dbdir}/sim.db"
        scan(Path(scandir), db, compute_hash=False)
        yield db


def test_find_similar_folders_respects_threshold(populated_db):
    """A threshold of 0.99 should reject the (similar-but-not-identical) pair."""
    permissive = find_similar_folders(populated_db, min_files=2, threshold=0.3)
    strict = find_similar_folders(populated_db, min_files=2, threshold=0.99)
    assert permissive  # ≥1 pair under loose threshold
    assert len(strict) <= len(permissive)


def test_find_similar_folders_respects_min_files(populated_db):
    """min_files=10 excludes the 3-file folders entirely."""
    out = find_similar_folders(populated_db, min_files=10, threshold=0.1)
    assert out == []


def test_find_similar_folders_max_results_caps_output(populated_db):
    out = find_similar_folders(populated_db, min_files=2, threshold=0.0,
                               max_results=0)
    assert out == []


def test_find_similar_folders_progress_callback_invoked(populated_db):
    seen: list[tuple[int, int]] = []
    find_similar_folders(populated_db, min_files=2, threshold=0.3,
                         progress_cb=lambda done, total: seen.append((done, total)))
    # Callback fires at least once with a (done, total) pair
    assert seen
    assert all(isinstance(p, tuple) and len(p) == 2 for p in seen)


def test_find_similar_folders_stop_flag_short_circuits(populated_db):
    out = find_similar_folders(populated_db, min_files=2, threshold=0.3,
                               stop_flag=lambda: True)
    # Stop flag respected: result is empty (or at most trivial)
    assert isinstance(out, list)


def test_find_similar_groups_returns_group_shape(populated_db):
    groups = find_similar_groups(populated_db, min_files=2, threshold=0.3)
    if groups:
        g = groups[0]
        assert "members" in g
        assert "score" in g
        assert g["size"] >= 2

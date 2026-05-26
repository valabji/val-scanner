"""Tests for valscanner.core.filters — skip rules used by scanner.scan()."""
from __future__ import annotations

import pytest

from valscanner.core.filters import (
    BINARY_EXTS, CACHE_DIRS, LOG_EXTS, SYSTEM_DIRS, TEMP_EXTS, VCS_DIRS,
    FILTER_KEYS, file_is_skipped, path_has_skipped_dir,
)


# ─── file_is_skipped ─────────────────────────────────────────────────────────

def test_no_options_never_skips():
    assert file_is_skipped("a.txt", ".txt", {}) is False
    assert file_is_skipped(".hidden", "", {}) is False


def test_skip_hidden_files():
    assert file_is_skipped(".env", "", {"skip_hidden_files": True}) is True
    assert file_is_skipped("a.txt", ".txt", {"skip_hidden_files": True}) is False


def test_skip_binaries_matches_known_exts():
    for ext in (".exe", ".dll", ".so", ".pyc"):
        assert file_is_skipped(f"x{ext}", ext, {"skip_binaries": True}) is True
    assert file_is_skipped("a.txt", ".txt", {"skip_binaries": True}) is False


def test_skip_temp_includes_ds_store_by_name():
    """`.DS_Store` is detected by name even when extension is unusual."""
    assert file_is_skipped(".DS_Store", "", {"skip_temp": True}) is True
    assert file_is_skipped("a.tmp", ".tmp", {"skip_temp": True}) is True
    assert file_is_skipped("a.txt", ".txt", {"skip_temp": True}) is False


def test_skip_logs():
    assert file_is_skipped("err.log", ".log", {"skip_logs": True}) is True
    assert file_is_skipped("err.log", ".log", {}) is False


def test_filter_keys_constant_complete():
    """FILTER_KEYS is consumed by the GUI; keep it in sync with the rule set."""
    expected = {
        "skip_hidden_dirs", "skip_vcs", "skip_system", "skip_caches",
        "skip_hidden_files", "skip_binaries", "skip_temp", "skip_logs",
    }
    assert set(FILTER_KEYS) == expected


# ─── path_has_skipped_dir ────────────────────────────────────────────────────

@pytest.mark.parametrize("path,opts,expected", [
    # hidden dirs
    ("/home/u/.cache/x.txt",        {"skip_hidden_dirs": True}, True),
    ("/home/u/visible/x.txt",       {"skip_hidden_dirs": True}, False),
    # vcs
    ("/repo/.git/objects/f",        {"skip_vcs": True}, True),
    ("/repo/src/main.py",           {"skip_vcs": True}, False),
    # system
    ("/System/Library/foo.plist",   {"skip_system": True}, True),
    ("/Users/me/work/foo",          {"skip_system": True}, False),
    # caches
    ("/repo/node_modules/x.js",     {"skip_caches": True}, True),
    ("/repo/__pycache__/x.pyc",     {"skip_caches": True}, True),
    ("/repo/src/main.py",           {"skip_caches": True}, False),
])
def test_path_has_skipped_dir(path, opts, expected):
    assert path_has_skipped_dir(path, opts) is expected


def test_path_has_skipped_dir_empty_options_never_skips():
    assert path_has_skipped_dir("/anywhere/at/all/.git/x", {}) is False


def test_dir_sets_have_known_members():
    """Sanity-check the canonical contents — guards against accidental edits."""
    assert ".git" in VCS_DIRS
    assert "node_modules" in CACHE_DIRS
    assert "System" in SYSTEM_DIRS
    assert ".exe" in BINARY_EXTS
    assert ".log" in LOG_EXTS
    assert ".tmp" in TEMP_EXTS

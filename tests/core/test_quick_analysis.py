"""Tests for valscanner.core.quick_analysis — heuristic folder classifier."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from valscanner.core.scanner import scan
from valscanner.core.quick_analysis import classify_folders, group_backup_copies
from valscanner.core.export import (
    export_quick_analysis_csv,
    export_quick_analysis_json,
)


@pytest.fixture
def mixed_tree(tmp_path: Path):
    """Build a scan tree with one folder of each classifiable shape."""
    root = tmp_path / "tree"
    root.mkdir()

    photos = root / "Photos2024"
    photos.mkdir()
    for i in range(20):
        (photos / f"img{i:02d}.jpg").write_bytes(b"\xff\xd8" + b"x" * 100)

    music = root / "Music"
    music.mkdir()
    for i in range(15):
        (music / f"track{i:02d}.mp3").write_bytes(b"ID3" + b"x" * 100)

    videos = root / "Movies"
    videos.mkdir()
    for i in range(12):
        (videos / f"clip{i:02d}.mp4").write_bytes(b"x" * 200)

    nodeproj = root / "webapp"
    nodeproj.mkdir()
    (nodeproj / "package.json").write_text('{"name":"webapp"}')
    (nodeproj / "index.js").write_text("module.exports = {};\n")
    (nodeproj / "README.md").write_text("# webapp\n")
    src = nodeproj / "src"
    src.mkdir()
    for i in range(15):
        (src / f"comp{i}.js").write_text("export default 1;\n")
    nm = nodeproj / "node_modules" / "react"
    nm.mkdir(parents=True)
    for i in range(50):
        (nm / f"f{i}.js").write_text("x")

    pyproj = root / "mylib"
    pyproj.mkdir()
    (pyproj / "pyproject.toml").write_text("[project]\nname = 'mylib'\n")
    pkg = pyproj / "mylib"
    pkg.mkdir()
    for i in range(15):
        (pkg / f"mod{i}.py").write_text("x = 1\n")

    # The scanner prunes hidden dirs from os.walk, so we use `.gitignore`
    # (a hidden *file* — still indexed) as the git-repo marker.
    gitrepo = root / "siterepo"
    gitrepo.mkdir()
    (gitrepo / ".gitignore").write_text("*.log\n")
    (gitrepo / "main.go").write_text("package main\n")
    (gitrepo / "README.md").write_text("# repo\n")
    src = gitrepo / "internal"
    src.mkdir()
    for i in range(10):
        (src / f"f{i}.go").write_text("package internal\n")

    docs = root / "Docs"
    docs.mkdir()
    for i in range(12):
        (docs / f"r{i}.pdf").write_bytes(b"%PDF-1.4" + b"x" * 80)

    db = str(tmp_path / "qa.db")
    scan(root, db, compute_hash=False)
    return db


def _by_folder_basename(results: list[dict]) -> dict[str, dict]:
    return {Path(r["folder"]).name: r for r in results}


def test_photo_library_detected(mixed_tree):
    results = classify_folders(mixed_tree, min_files=5)
    by = _by_folder_basename(results)
    assert "Photos2024" in by
    assert by["Photos2024"]["category"] == "photo-library"
    assert by["Photos2024"]["dominance"] >= 0.70


def test_music_library_detected(mixed_tree):
    by = _by_folder_basename(classify_folders(mixed_tree, min_files=5))
    assert by["Music"]["category"] == "music-library"


def test_video_library_detected(mixed_tree):
    by = _by_folder_basename(classify_folders(mixed_tree, min_files=5))
    assert by["Movies"]["category"] == "video-library"


def test_node_project_detected_and_node_modules_hidden(mixed_tree):
    results = classify_folders(mixed_tree, min_files=5)
    by = _by_folder_basename(results)
    assert "webapp" in by
    assert by["webapp"]["category"] == "node-project"
    # Folders inside node_modules/ must not surface.
    for r in results:
        assert "node_modules" not in r["folder"].replace("\\", "/").split("/")


def test_node_project_subtree_rollup(mixed_tree):
    """The project row should reflect the whole subtree, not just direct children."""
    by = _by_folder_basename(classify_folders(mixed_tree, min_files=5))
    webapp = by["webapp"]
    # 3 root files + 15 src + 50 node_modules = 68
    assert webapp["file_count"] >= 60


def test_python_project_detected(mixed_tree):
    by = _by_folder_basename(classify_folders(mixed_tree, min_files=5))
    assert by["mylib"]["category"] == "python-project"


def test_git_repo_detected(mixed_tree):
    """`.gitignore` presence should mark the folder as a git-repo project."""
    results = classify_folders(mixed_tree, min_files=3)
    by = _by_folder_basename(results)
    assert by["siterepo"]["category"] == "git-repo"


def test_documents_bin_detected(mixed_tree):
    by = _by_folder_basename(classify_folders(mixed_tree, min_files=5))
    assert by["Docs"]["category"] == "documents-bin"


def test_mixed_excluded_by_default(mixed_tree):
    results = classify_folders(mixed_tree, min_files=2)
    assert all(r["category"] != "mixed" for r in results)


def test_mixed_included_when_requested(mixed_tree):
    results = classify_folders(mixed_tree, min_files=2, include_mixed=True)
    # The scan root has a mix of subdirs but very few direct files; with
    # min_files=2 it won't show. Just verify the flag doesn't crash and
    # results stay structurally valid.
    assert all("category" in r for r in results)


def test_min_files_filters_small_folders(mixed_tree):
    results = classify_folders(mixed_tree, min_files=100)
    # No folder has 100 direct files in this fixture except via subtree rollup
    # (node project — 68). So even node-project should drop out.
    names = {Path(r["folder"]).name for r in results}
    assert "Photos2024" not in names
    assert "Music" not in names


@pytest.fixture
def nested_photo_tree(tmp_path: Path):
    """Photo library spread across nested folders + a node project sibling
    so we can verify the media-rollup behaviour without absorbing projects."""
    root = tmp_path / "tree"
    root.mkdir()

    device = root / "Y9_backup"
    device.mkdir()
    dcim = device / "DCIM" / "Camera"
    dcim.mkdir(parents=True)
    for i in range(15):
        (dcim / f"IMG_{i:03d}.jpg").write_bytes(b"\xff\xd8" + b"x" * 200)
    screenshots = device / "Pictures" / "Screenshots"
    screenshots.mkdir(parents=True)
    for i in range(10):
        (screenshots / f"Screenshot_{i:03d}.png").write_bytes(b"\x89PNG" + b"x" * 100)

    nested_proj = device / "webproj"
    nested_proj.mkdir()
    (nested_proj / "package.json").write_text('{"name":"x"}')
    for i in range(10):
        (nested_proj / f"f{i}.js").write_text("x")

    db = str(tmp_path / "nested.db")
    scan(root, db, compute_hash=False)
    return db


def test_media_subtree_rollup(nested_photo_tree):
    """A photo-library parent absorbs its photo-dominated descendants so
    only one row surfaces with combined file_count / total_bytes."""
    results = classify_folders(nested_photo_tree, min_files=5)
    photo_rows = [r for r in results if r["category"] == "photo-library"]
    by = {Path(r["folder"]).name: r for r in photo_rows}
    # The DCIM/Camera + Pictures/Screenshots subtrees should collapse into
    # Y9_backup (the outermost photo-dominated ancestor).
    assert "Y9_backup" in by
    parent = by["Y9_backup"]
    assert parent["file_count"] >= 25, (
        "Expected parent to roll up Camera (15) + Screenshots (10) = 25"
    )
    # The descendants must NOT appear as separate photo-library rows.
    assert "Camera" not in by
    assert "Screenshots" not in by
    assert "+" in (parent.get("subcategory") or ""), (
        "Rolled-up row should annotate the absorbed-subfolder count"
    )


def test_media_rollup_respects_project_roots(nested_photo_tree):
    """A node-project nested inside a photo-library parent must still surface
    as its own row — the photo rollup must not absorb projects."""
    results = classify_folders(nested_photo_tree, min_files=5)
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    assert "node-project" in by_cat, "node project must survive media rollup"
    proj_names = {Path(r["folder"]).name for r in by_cat["node-project"]}
    assert "webproj" in proj_names


def test_group_backup_copies_collapses_mirrors():
    """Two rows with same category, identical trailing suffix, and bytes
    within 5% collapse to one primary; the row with more files wins."""
    base = "Personal/Backups/My Personal Files/Photos/DCIM/Camera"
    rows = [
        {
            "scan_id": 1, "scan_label": "drive-N",
            "folder": "/Volumes/Valabji N/" + base,
            "category": "photo-library", "subcategory": "",
            "file_count": 1123, "total_bytes": 13_500_000_000,
            "dominance": 0.94,
        },
        {
            "scan_id": 2, "scan_label": "drive-01D4",
            "folder": "/run/media/valabji/01D40E0F1BF498A0/Should be secured/" + base,
            "category": "photo-library", "subcategory": "",
            "file_count": 1100, "total_bytes": 13_300_000_000,
            "dominance": 0.94,
        },
        {
            "scan_id": 3, "scan_label": "drive-X",
            "folder": "/Volumes/Other/Music/Library/Albums/Jazz",
            "category": "music-library", "subcategory": "",
            "file_count": 200, "total_bytes": 5_000_000_000,
            "dominance": 0.80,
        },
    ]
    out = group_backup_copies(rows)
    photo_rows = [r for r in out if r["category"] == "photo-library"]
    assert len(photo_rows) == 1, "two photo mirrors should collapse into one"
    primary = photo_rows[0]
    assert primary["file_count"] == 1123, "primary must be the more-complete copy"
    assert primary["has_mirrors"] is True
    assert primary["mirror_count"] == 1
    assert primary["mirrors"][0]["folder"].startswith("/run/media/")
    assert primary["mirrors"][0]["files_delta"] == 1100 - 1123
    # Unrelated music row passes through untouched.
    assert any(r["category"] == "music-library" for r in out)


def _sample_grouped_results() -> list[dict]:
    base = "MyFiles/Photos/DCIM/Camera"
    rows = [
        {
            "scan_id": 1, "scan_label": "drive-N",
            "folder": "/Volumes/N/" + base,
            "category": "photo-library", "subcategory": "jpg 94%",
            "file_count": 1123, "total_bytes": 13_500_000_000,
            "dominance": 0.94,
        },
        {
            "scan_id": 2, "scan_label": "drive-X",
            "folder": "/run/media/valabji/X/" + base,
            "category": "photo-library", "subcategory": "jpg 94%",
            "file_count": 1100, "total_bytes": 13_300_000_000,
            "dominance": 0.94,
        },
        {
            "scan_id": 3, "scan_label": "drive-Y",
            "folder": "/Volumes/Y/Music/Jazz",
            "category": "music-library", "subcategory": "",
            "file_count": 200, "total_bytes": 5_000_000_000,
            "dominance": 0.80,
        },
    ]
    return group_backup_copies(rows)


def test_export_quick_analysis_json_round_trip(tmp_path: Path):
    """JSON keeps the nested mirrors list with files_delta intact."""
    results = _sample_grouped_results()
    out = tmp_path / "qa.json"
    export_quick_analysis_json(results, str(out))

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert len(loaded) == len(results)

    photo = next(r for r in loaded if r["category"] == "photo-library")
    assert photo["file_count"] == 1123
    assert photo["mirrors"], "primary must carry its mirror list in JSON"
    assert photo["mirrors"][0]["folder"].startswith("/run/media/")
    assert photo["mirrors"][0]["files_delta"] == 1100 - 1123


def test_export_quick_analysis_csv_flattens_mirrors(tmp_path: Path):
    """CSV exposes mirror_count + mirror_paths instead of nested rows."""
    results = _sample_grouped_results()
    out = tmp_path / "qa.csv"
    export_quick_analysis_csv(results, str(out))

    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2, "music row + collapsed photo primary"
    expected_cols = {
        "scan_id", "scan_label", "folder", "category", "subcategory",
        "file_count", "total_bytes", "dominance",
        "mirror_count", "mirror_paths",
    }
    assert expected_cols.issubset(set(rows[0].keys()))

    photo = next(r for r in rows if r["category"] == "photo-library")
    assert photo["mirror_count"] == "1"
    assert photo["mirror_paths"].startswith("/run/media/")
    assert ";" not in photo["mirror_paths"], "only one mirror, no separator"

    music = next(r for r in rows if r["category"] == "music-library")
    assert music["mirror_count"] == "0"
    assert music["mirror_paths"] == ""


def test_group_backup_copies_skips_when_bytes_diverge():
    """Folders with the same suffix but >5% byte difference are NOT grouped —
    they may be different snapshots, not mirrors."""
    rows = [
        {
            "scan_id": 1, "scan_label": "a",
            "folder": "/A/Photos/2024/Camera",
            "category": "photo-library", "subcategory": "",
            "file_count": 500, "total_bytes": 10_000_000_000,
            "dominance": 0.9,
        },
        {
            "scan_id": 2, "scan_label": "b",
            "folder": "/B/Photos/2024/Camera",
            "category": "photo-library", "subcategory": "",
            "file_count": 500, "total_bytes": 5_000_000_000,
            "dominance": 0.9,
        },
    ]
    out = group_backup_copies(rows)
    assert len(out) == 2, "rows with >5% byte gap must stay separate"
    for r in out:
        assert not r.get("has_mirrors")

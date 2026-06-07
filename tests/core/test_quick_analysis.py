"""Tests for valscanner.core.quick_analysis — heuristic folder classifier."""
from __future__ import annotations

from pathlib import Path

import pytest

from valscanner.core.scanner import scan
from valscanner.core.quick_analysis import classify_folders


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

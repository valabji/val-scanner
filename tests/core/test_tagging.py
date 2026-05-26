"""Tests for valscanner.core.tagging.generate_tags."""
from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from valscanner.core.tagging import generate_tags


def tags(path: str, category: str = "", size: int = 0) -> set[str]:
    return set(generate_tags(PurePosixPath(path), category, size))


# ─── category branches ──────────────────────────────────────────────────────

def test_photo_yields_photos_and_media():
    t = tags("/u/IMG_1.jpg", "photo", 50_000)
    assert {"photo", "photos", "media"}.issubset(t)


def test_audio_video_yield_media():
    assert "media" in tags("/u/song.mp3", "audio", 1_000_000)
    assert "media" in tags("/u/clip.mp4", "video", 1_000_000)


def test_document_yields_documents_bucket():
    assert "documents" in tags("/u/report.docx", "document", 5000)


def test_code_yields_lang_tag():
    t = tags("/u/main.py", "code", 1000)
    assert "source-code" in t
    assert "lang-py" in t


def test_archive_and_executable_branches():
    assert "compressed" in tags("/u/x.zip", "archive", 100)
    assert "binary" in tags("/u/run.exe", "executable", 100)


# ─── size buckets ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("size,bucket", [
    (0, "empty-file"),
    (5_000, "tiny"),
    (500_000, "small"),
    (50 * 1024 * 1024, "medium"),
    (500 * 1024 * 1024, "large"),
    (2 * 1024 * 1024 * 1024, "huge"),
])
def test_size_buckets(size, bucket):
    assert bucket in tags("/u/x.bin", "", size)


# ─── folder keywords / parent-folder tag ────────────────────────────────────

def test_folder_keyword_downloads():
    assert "downloads-folder" in tags("/u/Downloads/x.zip", "archive", 100)


def test_parent_folder_tag_emitted():
    t = tags("/u/projects/myrepo/file.py", "code", 100)
    # Parent-folder tag is the literal directory name + "-folder"
    assert "myrepo-folder" in t


def test_dotfile_marks_hidden():
    t = tags("/u/.bashrc", "", 200)
    assert "hidden-file" in t
    assert "dotfile" in t


# ─── name keywords ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,tag", [
    ("resume_v2.pdf",   "resume"),
    ("invoice_2024.pdf", "invoice"),
    ("dockerfile",       "docker"),
    ("password.txt",     "sensitive"),
    ("budget_q1.xlsx",   "budget"),
    ("README.md",        "readme"),
])
def test_name_keyword_tag(name, tag):
    assert tag in tags(f"/u/{name}", "", 100)


# ─── extension-derived sub-tags ─────────────────────────────────────────────

def test_camera_photo_extension():
    assert "camera-photo" in tags("/u/IMG_0001.HEIC", "photo", 1_000_000)


def test_graphic_extension():
    assert "graphic" in tags("/u/logo.svg", "", 1000)


def test_modern_video_extension():
    assert "modern-video" in tags("/u/clip.mp4", "video", 100)


def test_music_file_extension():
    assert "music-file" in tags("/u/track.flac", "audio", 100)


def test_returns_sorted_list():
    out = generate_tags(PurePosixPath("/u/a.txt"), "document", 100)
    assert out == sorted(out)

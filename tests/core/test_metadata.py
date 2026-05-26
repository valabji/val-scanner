"""Tests for valscanner.core.metadata — extractors, hashing, and thumbnailing.

We exercise the real PIL/mutagen/pypdf paths when available, and the safe
graceful-degradation paths when libraries are absent or ffmpeg is missing.
The optional-feature flags themselves are sanity-checked as bools.
"""
from __future__ import annotations

import io
import struct

import pytest

from valscanner.core import metadata
from valscanner.core.metadata import (
    FFMPEG_AVAILABLE, MUTAGEN_AVAILABLE, PIL_AVAILABLE, PYPDF_AVAILABLE,
    extract_audio_metadata, extract_image_metadata, extract_pdf_metadata,
    file_sha256, _sample_media, _thumb_image, _thumb_video,
)


# ─── availability flags ─────────────────────────────────────────────────────

def test_availability_flags_are_booleans():
    """Flags must always be present and bool-typed for callers to branch on."""
    assert isinstance(PIL_AVAILABLE, bool)
    assert isinstance(MUTAGEN_AVAILABLE, bool)
    assert isinstance(PYPDF_AVAILABLE, bool)
    assert isinstance(FFMPEG_AVAILABLE, bool)


# ─── file_sha256 ────────────────────────────────────────────────────────────

def test_file_sha256_matches_expected_hex(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello world")
    # Known SHA-256 of "hello world"
    assert file_sha256(p) == (
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )


def test_file_sha256_empty_file(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    # Known SHA-256 of empty input
    assert file_sha256(p) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_file_sha256_returns_empty_string_on_missing(tmp_path):
    """A non-existent file should produce '' rather than raising."""
    assert file_sha256(tmp_path / "nope.bin") == ""


def test_file_sha256_respects_block_size(tmp_path):
    """Different block sizes must yield the same digest."""
    p = tmp_path / "blob.bin"
    p.write_bytes(b"a" * 200_000)
    h1 = file_sha256(p, block=1024)
    h2 = file_sha256(p, block=65536)
    assert h1 == h2 and len(h1) == 64


# ─── extract_image_metadata ─────────────────────────────────────────────────

@pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
def test_extract_image_metadata_real_png(tmp_path):
    from PIL import Image
    p = tmp_path / "x.png"
    Image.new("RGB", (32, 16), (255, 0, 0)).save(p)
    meta = extract_image_metadata(p)
    assert meta["img_width"] == 32
    assert meta["img_height"] == 16
    assert meta["img_format"] in ("PNG",)


def test_extract_image_metadata_returns_empty_on_bad_input(tmp_path):
    """Garbage input must never raise — caller treats {} as 'no metadata'."""
    p = tmp_path / "junk.png"
    p.write_bytes(b"not an image")
    assert extract_image_metadata(p) == {}


def test_extract_image_metadata_no_pil(tmp_path, monkeypatch):
    """When PIL is unavailable the extractor short-circuits to {}."""
    monkeypatch.setattr(metadata, "PIL_AVAILABLE", False)
    assert extract_image_metadata(tmp_path / "anything.jpg") == {}


# ─── extract_audio_metadata ─────────────────────────────────────────────────

def test_extract_audio_metadata_returns_empty_on_garbage(tmp_path):
    p = tmp_path / "bogus.mp3"
    p.write_bytes(b"\x00" * 64)
    assert extract_audio_metadata(p) == {}


def test_extract_audio_metadata_no_mutagen(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "MUTAGEN_AVAILABLE", False)
    assert extract_audio_metadata(tmp_path / "x.mp3") == {}


# ─── extract_pdf_metadata ───────────────────────────────────────────────────

def test_extract_pdf_metadata_returns_empty_on_garbage(tmp_path):
    p = tmp_path / "bogus.pdf"
    p.write_bytes(b"%PDF-not really")
    assert extract_pdf_metadata(p) == {}


def test_extract_pdf_metadata_no_pypdf(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "PYPDF_AVAILABLE", False)
    assert extract_pdf_metadata(tmp_path / "x.pdf") == {}


# ─── thumbnail helpers ──────────────────────────────────────────────────────

@pytest.mark.skipif(not PIL_AVAILABLE, reason="PIL not installed")
def test_thumb_image_round_trip(tmp_path):
    from PIL import Image
    src = tmp_path / "big.png"
    Image.new("RGB", (400, 300), (10, 20, 30)).save(src)
    thumb = _thumb_image(src, max_size=64, quality=70)
    assert isinstance(thumb, bytes) and thumb.startswith(b"\xff\xd8")  # JPEG SOI
    # Round-trip parses back to a JPEG within the requested bounds
    img = Image.open(io.BytesIO(thumb))
    assert max(img.size) <= 64


def test_thumb_image_no_pil_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "PIL_AVAILABLE", False)
    assert _thumb_image(tmp_path / "x.png", 64, 70) is None


def test_thumb_image_bad_input_returns_none(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"not an image")
    assert _thumb_image(p, 64, 70) is None


def test_thumb_video_no_ffmpeg_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", False)
    assert _thumb_video(tmp_path / "x.mp4", 64, 70) is None


def test_sample_media_no_ffmpeg_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", False)
    assert _sample_media(tmp_path / "x.mp3", "audio", 3) is None


def test_sample_media_subprocess_failure_returns_none(tmp_path, monkeypatch):
    """If ffmpeg exits non-zero or yields no bytes, return None gracefully."""
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", True)

    class _FakeResult:
        returncode = 1
        stdout = b""

    monkeypatch.setattr(metadata.subprocess, "run",
                        lambda *a, **kw: _FakeResult())
    assert _sample_media(tmp_path / "x.mp3", "audio", 3) is None
    assert _sample_media(tmp_path / "x.mp4", "video", 3) is None


def test_sample_media_subprocess_success_for_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", True)

    class _OkResult:
        returncode = 0
        stdout = b"FAKE-MP3-BYTES"

    monkeypatch.setattr(metadata.subprocess, "run",
                        lambda *a, **kw: _OkResult())
    out = _sample_media(tmp_path / "x.mp3", "audio", 3)
    assert out == (b"FAKE-MP3-BYTES", "mp3")

    # Video branch reaches success too
    out = _sample_media(tmp_path / "x.mp4", "video", 3)
    assert out == (b"FAKE-MP3-BYTES", "mp4")


def test_thumb_video_subprocess_success(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", True)

    class _OkResult:
        returncode = 0
        stdout = b"FAKE-JPEG-BYTES"

    monkeypatch.setattr(metadata.subprocess, "run",
                        lambda *a, **kw: _OkResult())
    assert _thumb_video(tmp_path / "x.mp4", 64, 70) == b"FAKE-JPEG-BYTES"


def test_sample_media_subprocess_raises(tmp_path, monkeypatch):
    """Any exception from subprocess.run is swallowed."""
    monkeypatch.setattr(metadata, "FFMPEG_AVAILABLE", True)

    def _boom(*a, **kw):
        raise OSError("no such binary")

    monkeypatch.setattr(metadata.subprocess, "run", _boom)
    assert _sample_media(tmp_path / "x.mp3", "audio", 3) is None
    assert _thumb_video(tmp_path / "x.mp4", 64, 70) is None

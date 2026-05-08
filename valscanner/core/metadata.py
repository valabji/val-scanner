from __future__ import annotations
import io
import hashlib
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import PyPDF2
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

FFMPEG_AVAILABLE = bool(shutil.which("ffmpeg"))


def extract_image_metadata(path: Path) -> dict:
    if not PIL_AVAILABLE:
        return {}
    try:
        with Image.open(path) as img:
            meta = {
                "img_width":  img.width,
                "img_height": img.height,
                "img_mode":   img.mode,
                "img_format": img.format,
            }
            exif_data = img._getexif() if hasattr(img, "_getexif") else None
            if exif_data:
                readable = {}
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, str(tag_id))
                    if isinstance(value, (str, int, float)):
                        readable[tag] = value
                if "DateTime" in readable:
                    meta["exif_datetime"] = readable["DateTime"]
                if "Make" in readable:
                    meta["exif_camera_make"] = readable["Make"]
                if "Model" in readable:
                    meta["exif_camera_model"] = readable["Model"]
                if "GPSInfo" in exif_data:
                    meta["has_gps"] = True
            return meta
    except Exception:
        return {}


def extract_audio_metadata(path: Path) -> dict:
    if not MUTAGEN_AVAILABLE:
        return {}
    try:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return {}
        meta = {}
        for key in ("title", "artist", "album", "date", "genre", "tracknumber"):
            if key in audio:
                meta[f"audio_{key}"] = ", ".join(audio[key])
        if hasattr(audio, "info"):
            info = audio.info
            if hasattr(info, "length"):
                meta["audio_duration_sec"] = round(info.length, 2)
            if hasattr(info, "bitrate"):
                meta["audio_bitrate"] = info.bitrate
        return meta
    except Exception:
        return {}


def extract_pdf_metadata(path: Path) -> dict:
    if not PYPDF_AVAILABLE:
        return {}
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            meta = {"pdf_pages": len(reader.pages)}
            info = reader.metadata
            if info:
                for k in ("/Title", "/Author", "/Subject", "/Creator", "/CreationDate"):
                    v = info.get(k)
                    if v:
                        meta[f"pdf_{k.strip('/').lower()}"] = str(v)
            return meta
    except Exception:
        return {}


def file_sha256(path: Path, block: int = 65536) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(block):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _thumb_image(fpath: Path, max_size: int, quality: int) -> bytes | None:
    if not PIL_AVAILABLE:
        return None
    try:
        img = Image.open(fpath)
        if img.mode == "P" and "transparency" in img.info:
            img = img.convert("RGBA")
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _thumb_video(fpath: Path, max_size: int, quality: int) -> bytes | None:
    if not FFMPEG_AVAILABLE:
        return None
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(fpath),
                "-ss", "00:00:01",
                "-vframes", "1",
                "-vf", f"scale={max_size}:{max_size}:force_original_aspect_ratio=decrease",
                "-q:v", str(max(1, (100 - quality) // 10)),
                "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True, timeout=30,
        )
        return result.stdout if result.returncode == 0 and result.stdout else None
    except Exception:
        return None


def _sample_media(fpath: Path, category: str, duration: int) -> tuple[bytes, str] | None:
    if not FFMPEG_AVAILABLE:
        return None
    try:
        if category == "video":
            cmd = [
                "ffmpeg", "-y", "-i", str(fpath),
                "-t", str(duration),
                "-vf", "scale=320:-2",
                "-c:v", "libx264", "-crf", "35", "-preset", "ultrafast",
                "-c:a", "aac", "-b:a", "32k",
                "-movflags", "frag_keyframe+empty_moov",
                "-f", "mp4", "pipe:1",
            ]
            fmt = "mp4"
        else:
            cmd = [
                "ffmpeg", "-y", "-i", str(fpath),
                "-t", str(duration),
                "-c:a", "libmp3lame", "-b:a", "32k",
                "-f", "mp3", "pipe:1",
            ]
            fmt = "mp3"
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode == 0 and result.stdout:
            return result.stdout, fmt
    except Exception:
        pass
    return None

from __future__ import annotations
import io
import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

if PIL_AVAILABLE:
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    try:
        import pillow_avif  # noqa: F401  (registers AVIF opener on import)
    except ImportError:
        pass

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    SVGLIB_AVAILABLE = True
except ImportError:
    SVGLIB_AVAILABLE = False

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
            reader = pypdf.PdfReader(f)
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


def file_sha256(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    try:
        buf = bytearray(block)
        mv = memoryview(buf)
        with open(path, "rb", buffering=0) as f:
            while True:
                n = f.readinto(buf)
                if not n:
                    break
                h.update(mv[:n] if n < block else mv)
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


def _thumb_svg(fpath: Path, max_size: int, quality: int) -> bytes | None:
    if not (SVGLIB_AVAILABLE and PIL_AVAILABLE):
        return None
    try:
        drawing = svg2rlg(str(fpath))
        if drawing is None or drawing.width <= 0 or drawing.height <= 0:
            return None
        scale = max_size / max(drawing.width, drawing.height)
        if scale < 1:
            drawing.width *= scale
            drawing.height *= scale
            drawing.scale(scale, scale)
        png_bytes = renderPM.drawToString(drawing, fmt="PNG", bg=0xFFFFFF)
        img = Image.open(io.BytesIO(png_bytes))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as e:
        _log.warning("[thumb_svg] %s: %s", fpath, e)
        return None


def _thumb_video(fpath: Path, max_size: int, quality: int) -> bytes | None:
    if not FFMPEG_AVAILABLE:
        return None
    qv = str(max(1, (100 - quality) // 10))
    vf = f"scale={max_size}:{max_size}:force_original_aspect_ratio=decrease"
    last_err: bytes = b""
    last_rc: int = 0
    for seek in ("00:00:01", "0"):
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", seek, "-i", str(fpath),
                    "-vframes", "1",
                    "-vf", vf,
                    "-q:v", qv,
                    "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
                ],
                capture_output=True, timeout=30,
            )
        except Exception as e:
            _log.warning("[thumb_video] %s: %s", fpath, e)
            return None
        if result.returncode == 0 and result.stdout:
            return result.stdout
        last_rc = result.returncode
        last_err = result.stderr or b""
    _log.warning("[thumb_video] %s: ffmpeg rc=%d — %s",
                 fpath, last_rc,
                 last_err[-400:].decode("utf-8", "replace").strip())
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
        _log.warning("[sample_media] %s: ffmpeg rc=%d stdout=%d bytes — %s",
                     fpath, result.returncode, len(result.stdout or b""),
                     (result.stderr or b"")[-400:].decode("utf-8", "replace").strip())
    except Exception as e:
        _log.warning("[sample_media] %s: %s", fpath, e)
    return None

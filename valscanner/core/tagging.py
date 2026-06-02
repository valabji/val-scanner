from __future__ import annotations
import re
from pathlib import Path

# Module-level constants — hoisted out of generate_tags() so the dict and tuple
# literals aren't reallocated on every single file scanned.

_FOLDER_KEYWORDS = {
    "download": "downloads-folder", "downloads": "downloads-folder",
    "desktop": "desktop-folder", "documents": "documents-folder",
    "pictures": "pictures-folder", "photos": "photos-folder",
    "music": "music-folder", "videos": "videos-folder",
    "movies": "movies-folder", "backup": "backup", "backups": "backup",
    "archive": "archived", "old": "old-files", "temp": "temp-files",
    "tmp": "temp-files", "cache": "cached", "logs": "log-files",
    "work": "work", "projects": "projects", "project": "projects",
    "personal": "personal", "private": "private", "shared": "shared",
    "screenshots": "screenshots", "wallpapers": "wallpapers",
    "fonts": "fonts", "icons": "icons", "assets": "assets",
    "src": "source-code", "source": "source-code", "bin": "binaries",
    "lib": "libraries", "node_modules": "node-modules",
    "venv": "python-venv", ".git": "git-repo",
}

_NAME_KEYWORDS = {
    "resume": "resume", "cv": "resume", "invoice": "invoice",
    "receipt": "receipt", "contract": "contract",
    "screenshot": "screenshot", "screen shot": "screenshot",
    "wallpaper": "wallpaper", "backup": "backup", "draft": "draft",
    "final": "final-version", "readme": "readme", "changelog": "changelog",
    "license": "license", "makefile": "build-file", "dockerfile": "docker",
    "setup": "installer", "install": "installer", "log": "log-file",
    "config": "config-file", "settings": "config-file",
    "test": "test-file", "spec": "test-file", "notes": "notes",
    "todo": "todo", "report": "report", "summary": "summary",
    "plan": "plan", "budget": "budget", "tax": "tax",
    "password": "sensitive", "secret": "sensitive", "private": "sensitive",
    "img": "image", "photo": "photo", "pic": "photo",
    "video": "video", "music": "audio", "song": "audio",
    "album": "audio", "book": "ebook",
}

_DOC_CATEGORIES = frozenset(("document", "spreadsheet", "presentation", "ebook"))
_MEDIA_CATEGORIES = frozenset(("video", "audio"))
_CAMERA_EXTS = frozenset((".jpg", ".jpeg", ".heic", ".heif", ".raw", ".cr2", ".nef"))
_GRAPHIC_EXTS = frozenset((".png", ".svg", ".webp"))
_MODERN_VIDEO_EXTS = frozenset((".mp4", ".mov", ".m4v"))
_MUSIC_EXTS = frozenset((".mp3", ".flac", ".m4a", ".aac"))
_SKIP_PARENTS = frozenset((".", "/", "\\"))

_SIZE_TINY = 10 * 1024
_SIZE_SMALL = 1024 * 1024
_SIZE_MEDIUM = 100 * 1024 * 1024
_SIZE_LARGE = 1024 * 1024 * 1024


# Single-pass keyword matcher: scans the filename stem once instead of running
# N independent `if kw in stem` substring searches per file. Keywords are
# sorted longest-first so "screen shot" wins over "screen"/"shot" and the
# regex engine picks the most specific alternative greedily.
_NAME_KEYWORDS_REGEX = re.compile(
    "|".join(re.escape(k) for k in sorted(_NAME_KEYWORDS, key=len, reverse=True))
)


def generate_tags(filepath: Path, category: str, size: int) -> list[str]:
    tags: set[str] = set()
    name_lower  = filepath.name.lower()
    stem_lower  = filepath.stem.lower()

    if category:
        tags.add(category)
    if category == "photo":
        tags.add("photos")
        tags.add("media")
    elif category in _MEDIA_CATEGORIES:
        tags.add("media")
    elif category in _DOC_CATEGORIES:
        tags.add("documents")
    elif category == "code":
        tags.add("source-code")
        ext = filepath.suffix.lower().lstrip(".")
        if ext:
            tags.add(f"lang-{ext}")
    elif category == "archive":
        tags.add("compressed")
    elif category == "executable":
        tags.add("binary")

    if size == 0:
        tags.add("empty-file")
    elif size < _SIZE_TINY:
        tags.add("tiny")
    elif size < _SIZE_SMALL:
        tags.add("small")
    elif size < _SIZE_MEDIUM:
        tags.add("medium")
    elif size < _SIZE_LARGE:
        tags.add("large")
    else:
        tags.add("huge")

    parts = filepath.parts
    for part in parts:
        pl = part.lower()
        kw = _FOLDER_KEYWORDS.get(pl)
        if kw is not None:
            tags.add(kw)
    if len(parts) >= 2:
        parent_name = parts[-2]
        if parent_name not in _SKIP_PARENTS:
            tags.add(f"{parent_name}-folder")

    for m in _NAME_KEYWORDS_REGEX.findall(stem_lower):
        tags.add(_NAME_KEYWORDS[m])

    if name_lower.startswith("."):
        tags.add("hidden-file")
        tags.add("dotfile")

    ext = filepath.suffix.lower()
    if ext in _CAMERA_EXTS:
        tags.add("camera-photo")
    if ext in _GRAPHIC_EXTS:
        tags.add("graphic")
    if ext in _MODERN_VIDEO_EXTS:
        tags.add("modern-video")
    if ext in _MUSIC_EXTS:
        tags.add("music-file")

    return sorted(tags)

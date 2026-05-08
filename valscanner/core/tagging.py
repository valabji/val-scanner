from __future__ import annotations
from pathlib import Path


def generate_tags(filepath: Path, category: str, size: int) -> list[str]:
    tags: set[str] = set()
    name_lower  = filepath.name.lower()
    stem_lower  = filepath.stem.lower()
    parts_lower = [p.lower() for p in filepath.parts]

    if category:
        tags.add(category)
    if category == "photo":
        tags.add("photos")
        tags.add("media")
    if category in ("video", "audio"):
        tags.add("media")
    if category in ("document", "spreadsheet", "presentation", "ebook"):
        tags.add("documents")
    if category == "code":
        tags.add("source-code")
        ext = filepath.suffix.lower().lstrip(".")
        if ext:
            tags.add(f"lang-{ext}")
    if category == "archive":
        tags.add("compressed")
    if category == "executable":
        tags.add("binary")

    if size == 0:
        tags.add("empty-file")
    elif size < 10 * 1024:
        tags.add("tiny")
    elif size < 1024 * 1024:
        tags.add("small")
    elif size < 100 * 1024 * 1024:
        tags.add("medium")
    elif size < 1024 * 1024 * 1024:
        tags.add("large")
    else:
        tags.add("huge")

    folder_keywords = {
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
    for part in parts_lower:
        if part in folder_keywords:
            tags.add(folder_keywords[part])
    if len(filepath.parts) >= 2:
        parent_name = filepath.parts[-2]
        if parent_name not in (".", "/", "\\"):
            tags.add(f"{parent_name}-folder")

    name_keywords = {
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
    for kw, tag in name_keywords.items():
        if kw in stem_lower:
            tags.add(tag)

    if name_lower.startswith("."):
        tags.add("hidden-file")
        tags.add("dotfile")

    ext = filepath.suffix.lower()
    if ext in (".jpg", ".jpeg", ".heic", ".heif", ".raw", ".cr2", ".nef"):
        tags.add("camera-photo")
    if ext in (".png", ".svg", ".webp"):
        tags.add("graphic")
    if ext in (".mp4", ".mov", ".m4v"):
        tags.add("modern-video")
    if ext in (".mp3", ".flac", ".m4a", ".aac"):
        tags.add("music-file")

    return sorted(tags)

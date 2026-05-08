from __future__ import annotations

MIME_CATEGORY: dict[str, str] = {
    "image":       "photo",
    "video":       "video",
    "audio":       "audio",
    "text":        "document",
    "application": "application",
}

EXT_CATEGORY: dict[str, str] = {
    # Documents
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".odt": "document", ".rtf": "document", ".txt": "document",
    ".md":  "document", ".rst": "document", ".tex": "document",
    # Spreadsheets
    ".xls": "spreadsheet", ".xlsx": "spreadsheet", ".ods": "spreadsheet",
    ".csv": "spreadsheet",
    # Presentations
    ".ppt": "presentation", ".pptx": "presentation", ".odp": "presentation",
    # Photos / images
    ".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".gif": "photo",
    ".bmp": "photo", ".tiff": "photo", ".tif": "photo", ".webp": "photo",
    ".heic": "photo", ".heif": "photo", ".raw": "photo", ".cr2": "photo",
    ".nef": "photo", ".svg": "image",
    # Video
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".wmv": "video", ".flv": "video", ".webm": "video", ".m4v": "video",
    # Audio
    ".mp3": "audio", ".flac": "audio", ".wav": "audio", ".aac": "audio",
    ".ogg": "audio", ".m4a": "audio", ".wma": "audio",
    # Code
    ".py": "code",  ".js": "code",  ".ts": "code",  ".java": "code",
    ".c":  "code",  ".cpp": "code", ".h":  "code",  ".cs": "code",
    ".go": "code",  ".rs": "code",  ".rb": "code",  ".php": "code",
    ".sh": "code",  ".bat": "code", ".ps1": "code",
    # Data
    ".json": "data", ".xml": "data", ".yaml": "data", ".yml": "data",
    ".toml": "data", ".ini": "data", ".sql": "data",
    # Archives
    ".zip": "archive", ".tar": "archive", ".gz": "archive", ".bz2": "archive",
    ".7z": "archive",  ".rar": "archive", ".xz": "archive",
    # Executables / installers
    ".exe": "executable", ".msi": "executable", ".dmg": "executable",
    ".deb": "executable", ".rpm": "executable", ".appimage": "executable",
    # Fonts
    ".ttf": "font", ".otf": "font", ".woff": "font", ".woff2": "font",
    # Ebooks
    ".epub": "ebook", ".mobi": "ebook", ".azw": "ebook",
}

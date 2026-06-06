from __future__ import annotations
from pathlib import PurePath


SYSTEM_DIRS = frozenset({
    # macOS
    "System", "Library", "private", "usr", "bin", "sbin", "dev", "Volumes",
    "cores", "net", "home",
    # Windows
    "Windows", "System32", "SysWOW64", "Program Files", "Program Files (x86)",
    "ProgramData", "AppData", "Recovery", "MSOCache",
    # Linux
    "proc", "sys", "run", "snap",
})

CACHE_DIRS = frozenset({
    "__pycache__", "node_modules", ".gradle", ".m2", ".ivy2",
    "build", "dist", ".next", ".nuxt", "target", ".tox",
    "venv", ".venv", "env", ".eggs", "site-packages",
    ".sass-cache", "coverage", ".nyc_output", "DerivedData",
    ".build", "Pods", "bower_components", ".yarn", ".pnpm-store",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

VCS_DIRS = frozenset({
    ".git", ".svn", ".hg", ".bzr", "_darcs", "CVS", ".fossil",
})

BINARY_EXTS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib",
    ".obj", ".class", ".pyc", ".pyo", ".pyd", ".wasm",
    ".out", ".elf", ".ko", ".sys",
})

TEMP_EXTS = frozenset({
    ".tmp", ".temp", ".swp", ".swo", ".swn", ".bak", ".orig",
    ".~lock", ".DS_Store",
})

LOG_EXTS = frozenset({
    ".log",
})


FILTER_KEYS = (
    "skip_hidden_dirs", "skip_vcs", "skip_system", "skip_caches",
    "skip_hidden_files", "skip_binaries", "skip_temp", "skip_logs",
)


def file_is_skipped(filename: str, extension: str, options: dict) -> bool:
    if options.get("skip_hidden_files") and filename.startswith("."):
        return True
    if options.get("skip_binaries") and extension in BINARY_EXTS:
        return True
    if options.get("skip_temp") and (extension in TEMP_EXTS or filename == ".DS_Store"):
        return True
    if options.get("skip_logs") and extension in LOG_EXTS:
        return True
    return False


def path_has_skipped_dir(path_str: str, options: dict) -> bool:
    return _any_part_skipped(PurePath(path_str).parent.parts, options)


def path_contains_skipped_dir(path_str: str, options: dict) -> bool:
    # Like path_has_skipped_dir, but checks the leaf too — use for folder rows
    # where the basename IS the folder being judged (e.g. ".../.git").
    return _any_part_skipped(PurePath(path_str).parts, options)


def _any_part_skipped(parts, options: dict) -> bool:
    for part in parts:
        if not part or part in ("/", "\\"):
            continue
        if options.get("skip_hidden_dirs") and part.startswith("."):
            return True
        if options.get("skip_vcs") and part in VCS_DIRS:
            return True
        if options.get("skip_system") and part in SYSTEM_DIRS:
            return True
        if options.get("skip_caches") and part in CACHE_DIRS:
            return True
    return False

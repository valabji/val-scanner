"""Heuristic per-folder classification.

Single-pass classifier that buckets each folder into well-known categories
(photo / music / video libraries, code project roots, archive dumps, etc.)
without doing any pairwise comparison. Runs in O(files) time so it stays
useful at millions-of-files scale where the full similarity scorer
(`similarity.find_similar_folders`) is too expensive to wait for.

Classification rules — applied in this order per folder:

1. **Project root** if a marker file (`package.json`, `pom.xml`,
   `pyproject.toml`, `Cargo.toml`, …) sits directly in the folder, or if
   the folder is the parent of a marker directory (`.git`, `node_modules`).
2. **Media library** if the dominant file category (photo / audio / video /
   archive / document) clears its dominance threshold.
3. Otherwise **mixed** — surfaced only when explicitly requested.

Folders living *under* a known marker directory (e.g. anything inside
`node_modules/`) are hidden from results; their project root surfaces
instead, with rolled-up subtree totals so a tiny `package.json`-only folder
isn't reported as "12 KB" when the project is 400 MB.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Callable

from .categories import EXT_CATEGORY
from .db import repo_for
from .filters import file_is_skipped, path_has_skipped_dir


# Marker files: filename → project category assigned to the folder
# directly containing the file. Priority is resolved via PROJECT_PRIORITY
# below when several markers coexist.
MARKER_FILES: dict[str, str] = {
    # `.git/` itself is hidden and gets pruned by the scanner, so `.gitignore`
    # is the practical signal for "this folder is a git repo root".
    ".gitignore":       "git-repo",
    "package.json":     "node-project",
    "pom.xml":          "maven-project",
    "build.gradle":     "maven-project",
    "build.gradle.kts": "maven-project",
    "pyproject.toml":   "python-project",
    "setup.py":         "python-project",
    "requirements.txt": "python-project",
    "Cargo.toml":       "rust-project",
}

# Marker directories: when seen as a path segment, the *parent* of that
# segment is the project root. The marker dir itself and everything
# below it is suppressed from results.
MARKER_DIRS: dict[str, str] = {
    ".git":         "git-repo",
    "node_modules": "node-project",
}

# Project priority — the highest-priority match wins when a folder has
# several markers (e.g. a node project also tracked in git).
PROJECT_PRIORITY: tuple[str, ...] = (
    "git-repo",
    "node-project",
    "python-project",
    "rust-project",
    "maven-project",
)

# Media-library buckets: category-label → set of EXT_CATEGORY values that
# count toward the bucket. A folder qualifies if the bucket's share of its
# direct files clears MEDIA_DOMINANCE[label].
MEDIA_BUCKETS: dict[str, set[str]] = {
    "photo-library":  {"photo", "image"},
    "music-library":  {"audio"},
    "video-library":  {"video"},
    "archive-dump":   {"archive"},
    "documents-bin":  {"document", "spreadsheet", "presentation", "ebook"},
}

MEDIA_DOMINANCE: dict[str, float] = {
    "photo-library":  0.70,
    "music-library":  0.70,
    "video-library":  0.50,
    "archive-dump":   0.70,
    "documents-bin":  0.70,
}

# Display order used by CLI / future GUI summaries.
CATEGORY_ORDER: tuple[str, ...] = (
    "git-repo",
    "node-project",
    "python-project",
    "rust-project",
    "maven-project",
    "photo-library",
    "music-library",
    "video-library",
    "documents-bin",
    "archive-dump",
    "mixed",
)


def _parent(path: str) -> str:
    """Return the parent directory of `path`. Handles both POSIX and
    Windows separators without paying for a full Path() construction."""
    i = max(path.rfind("/"), path.rfind("\\"))
    return path[:i] if i > 0 else ""


def _split_segments(path: str) -> list[str]:
    return path.replace("\\", "/").split("/")


def _resolve_project_type(marker_hits: set[str], dir_hits: set[str]) -> str:
    """Pick the strongest project-type signal from file/dir markers."""
    candidates: set[str] = set()
    for fname in marker_hits:
        candidates.add(MARKER_FILES[fname])
    for d in dir_hits:
        candidates.add(MARKER_DIRS[d])
    for label in PROJECT_PRIORITY:
        if label in candidates:
            return label
    return next(iter(candidates))  # unreachable in practice; satisfies type checker


def _classify_media(cat_counts: Counter, total: int) -> tuple[str, float]:
    """Return (category, dominance) for media classification, or
    ("mixed", 0.0) if nothing dominates."""
    best_label = "mixed"
    best_pct = 0.0
    for label, buckets in MEDIA_BUCKETS.items():
        share = sum(cat_counts.get(b, 0) for b in buckets) / total
        if share >= MEDIA_DOMINANCE[label] and share > best_pct:
            best_label = label
            best_pct = share
    return best_label, best_pct


def classify_folders(
    db_path: str,
    scan_ids: list[int] | None = None,
    min_files: int = 10,
    filters: dict | None = None,
    include_mixed: bool = False,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Classify every folder in the given scan(s) by heuristic rules.

    Single streaming pass over `files` + a rollup pass over per-folder
    aggregates. Memory is bounded by the number of distinct parent
    folders, not the file count.

    Returns: list of dicts with fields `scan_id`, `scan_label`, `folder`,
    `category`, `subcategory` (markers/dominance description),
    `file_count`, `total_bytes`, `dominance`. The project-type rows carry
    *subtree* totals (rolled up across all descendant folders) so a
    `package.json`-only folder reflects the whole project size, not just
    its direct children.
    """
    repo = repo_for(db_path)
    rows = repo.iter_similarity_rows(scan_ids=scan_ids)

    fopts = filters or {}
    apply_filters = any(fopts.get(k) for k in (
        "skip_hidden_files", "skip_hidden_dirs", "skip_system", "skip_caches",
        "skip_vcs", "skip_binaries", "skip_temp", "skip_logs",
    ))

    # Per-folder direct-children aggregates.
    folders: dict = defaultdict(lambda: {
        "count": 0, "total_bytes": 0,
        "cats": Counter(),
        "marker_files": set(),
        "scan_id": 0, "scan_label": "",
    })

    n_rows = 0
    for r in rows:
        n_rows += 1
        if progress_cb and (n_rows & 0xFFFF) == 0:
            progress_cb(n_rows, 0)

        if apply_filters:
            ext = (r["extension"] or "").lower()
            if ext.startswith("(") or ext == "":
                ext = ""
            if file_is_skipped(r["filename"] or "", ext, fopts):
                continue
            if path_has_skipped_dir(r["path"], fopts):
                continue

        path     = r["path"]
        parent   = _parent(path)
        scan_id  = r["scan_id"]
        key      = (scan_id, parent)

        d = folders[key]
        d["scan_id"]    = scan_id
        d["scan_label"] = r["scan_label"]
        d["count"]       += 1
        d["total_bytes"] += r["size_bytes"] or 0

        ext = (r["extension"] or "").lower()
        d["cats"][EXT_CATEGORY.get(ext, "other")] += 1

        fname = r["filename"] or ""
        if fname in MARKER_FILES:
            d["marker_files"].add(fname)

    if progress_cb:
        progress_cb(n_rows, n_rows)

    # ── Marker-dir walk: find project roots via .git/, node_modules/, etc.
    # Also record which folders sit *inside* such a tree so we can hide them
    # from the final result list.
    project_dir_hits: dict[tuple[int, str], set[str]] = defaultdict(set)
    inside_marker: set[tuple[int, str]] = set()

    for (sid, parent), _d in folders.items():
        if not parent:
            continue
        parts = _split_segments(parent)
        for i, seg in enumerate(parts):
            if seg in MARKER_DIRS:
                inside_marker.add((sid, parent))
                # outermost segment is the strongest signal: that's the project root
                root_path = "/".join(parts[:i])
                project_dir_hits[(sid, root_path)].add(seg)
                break

    # ── Roll up subtree totals for any folder that's a project root.
    # Iterate folders once, sorted by path, then for each project root
    # collect descendants. Keeps it simple and O(projects × folders).
    project_keys: set[tuple[int, str]] = set(project_dir_hits.keys())
    for key, d in folders.items():
        if d["marker_files"]:
            project_keys.add(key)

    subtree: dict[tuple[int, str], tuple[int, int]] = {}
    if project_keys:
        # Bucket folders by scan_id for cheap inner loop.
        folders_by_scan: dict[int, list] = defaultdict(list)
        for (sid, parent), d in folders.items():
            folders_by_scan[sid].append((parent, d["count"], d["total_bytes"]))

        for pr_key in project_keys:
            sid, pr_path = pr_key
            tot_files = 0
            tot_bytes = 0
            pr_slash_fwd = pr_path + "/"
            pr_slash_bwd = pr_path + "\\"
            for fparent, fcount, fbytes in folders_by_scan.get(sid, ()):
                if (fparent == pr_path
                        or fparent.startswith(pr_slash_fwd)
                        or fparent.startswith(pr_slash_bwd)):
                    tot_files += fcount
                    tot_bytes += fbytes
            subtree[pr_key] = (tot_files, tot_bytes)

    # ── Build final result list.
    results: list[dict] = []
    for key, d in folders.items():
        sid, parent = key
        # Suppress folders inside a known marker tree (the project root
        # surfaces instead). Project roots themselves are not in
        # `inside_marker` because the parent path doesn't contain the
        # marker segment.
        if key in inside_marker and key not in project_keys:
            continue

        marker_files = d["marker_files"]
        dir_hits     = project_dir_hits.get(key, set())
        is_project   = bool(marker_files or dir_hits)

        if is_project:
            category   = _resolve_project_type(marker_files, dir_hits)
            sub_parts: list[str] = []
            if marker_files:
                sub_parts.append("+".join(sorted(marker_files)))
            if dir_hits:
                sub_parts.append("dir:" + "+".join(sorted(dir_hits)))
            subcategory = ", ".join(sub_parts)
            dominance   = 1.0
            sub_files, sub_bytes = subtree.get(key, (d["count"], d["total_bytes"]))
            file_count  = sub_files
            total_bytes = sub_bytes
            if file_count < min_files:
                continue
        else:
            if d["count"] < min_files:
                continue
            category, dominance = _classify_media(d["cats"], d["count"])
            if category == "mixed" and not include_mixed:
                continue
            subcategory = ""
            file_count  = d["count"]
            total_bytes = d["total_bytes"]

        results.append({
            "scan_id":     sid,
            "scan_label":  d["scan_label"],
            "folder":      parent,
            "category":    category,
            "subcategory": subcategory,
            "file_count":  file_count,
            "total_bytes": total_bytes,
            "dominance":   round(dominance, 3),
        })

    # Sort by category-display-order then size desc.
    cat_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    results.sort(key=lambda r: (cat_rank.get(r["category"], len(CATEGORY_ORDER)),
                                -r["total_bytes"]))
    return results

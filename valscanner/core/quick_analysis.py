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

    # One-category-per-path: any folder whose strict ancestor is a project
    # root is owned by that ancestor — its own classification (project or
    # media) is suppressed. Handles React-Native-style trees where the outer
    # repo has package.json and an inner `android/` carries build.gradle.
    descendant_of_project: set[tuple[int, str]] = set()
    if project_keys:
        proj_by_scan: dict[int, list[str]] = defaultdict(list)
        for (sid_p, pr_path) in project_keys:
            if pr_path:
                proj_by_scan[sid_p].append(pr_path)
        for sid_p in proj_by_scan:
            proj_by_scan[sid_p].sort(key=len)
        for (sid_f, fparent) in folders.keys():
            if not fparent:
                continue
            for pr_path in proj_by_scan.get(sid_f, ()):
                if fparent == pr_path:
                    continue
                if (fparent.startswith(pr_path + "/")
                        or fparent.startswith(pr_path + "\\")):
                    descendant_of_project.add((sid_f, fparent))
                    break
    # The descendant projects themselves no longer count as "real" project
    # roots — drop them so their subtree rollup never runs.
    project_keys -= descendant_of_project

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

    # ── Media-library subtree rollup.
    # Step 1: identify "media leaves" — folders whose direct files dominate
    # to one of the media categories.
    media_leaves: dict[tuple[int, str], tuple[str, float]] = {}
    for key, d in folders.items():
        if key in inside_marker and key not in project_keys:
            continue
        if key in project_keys:
            continue
        if key in descendant_of_project:
            continue
        if d["count"] < min_files:
            continue
        label, dom = _classify_media(d["cats"], d["count"])
        if label == "mixed":
            continue
        media_leaves[key] = (label, dom)

    # Step 2: per-scan, fetch the scan root path so we can cap rollup
    # below it (we never collapse to or above the user's scan boundary).
    scan_roots: dict[int, str] = {}
    if media_leaves:
        try:
            for s in repo.list_scans():
                scan_roots[int(s["id"])] = str(s.get("root") or "")
        except Exception:
            scan_roots = {}

    # Step 3: walk each leaf's ancestor chain and record, for every
    # ancestor, the set of media labels present below it and the number
    # of distinct leaves it contains.
    ancestor_labels: dict[tuple[int, str], set[str]] = defaultdict(set)
    ancestor_leaf_count: dict[tuple[int, str], int] = defaultdict(int)
    for leaf_key, (label, _) in media_leaves.items():
        sid, leaf_path = leaf_key
        p = _parent(leaf_path)
        while p:
            akey = (sid, p)
            ancestor_labels[akey].add(label)
            ancestor_leaf_count[akey] += 1
            np = _parent(p)
            if np == p:
                break
            p = np

    # Step 4: for each leaf, pick the highest ancestor that satisfies:
    #   - it is strictly below the scan root,
    #   - all media leaves under it share the leaf's label,
    #   - it contains at least 2 distinct media leaves (otherwise rollup
    #     is just a rename — keep the leaf as-is),
    #   - it is not inside a project tree and is not itself a project root.
    rollup_root: dict[tuple[int, str], tuple[int, str]] = {}
    for leaf_key, (label, _) in media_leaves.items():
        sid, leaf_path = leaf_key
        scan_root = scan_roots.get(sid, "")
        best = leaf_key
        p = _parent(leaf_path)
        while p:
            if scan_root and (p == scan_root or len(p) <= len(scan_root)):
                break
            akey = (sid, p)
            if (akey not in inside_marker
                    and akey not in project_keys
                    and ancestor_labels.get(akey) == {label}
                    and ancestor_leaf_count.get(akey, 0) >= 2):
                best = akey
            np = _parent(p)
            if np == p:
                break
            p = np
        rollup_root[leaf_key] = best

    # Step 5: per unique rollup root, aggregate descendant counts/bytes.
    media_root_data: dict[tuple[int, str], dict] = {}
    media_absorbed: set[tuple[int, str]] = set()
    folders_by_scan_paths: dict[int, list[str]] = defaultdict(list)
    for (sid, parent) in folders.keys():
        folders_by_scan_paths[sid].append(parent)
    for sid in folders_by_scan_paths:
        folders_by_scan_paths[sid].sort()

    roots = set(rollup_root.values())
    for root_key in roots:
        sid, root_path = root_key
        if root_key in media_leaves:
            label, dom = media_leaves[root_key]
        else:
            labels = ancestor_labels.get(root_key, set())
            if not labels:
                continue
            label = next(iter(labels))
            dom = 1.0
        if root_key in folders:
            tot_files = folders[root_key]["count"]
            tot_bytes = folders[root_key]["total_bytes"]
            scan_label = folders[root_key]["scan_label"]
        else:
            tot_files = 0
            tot_bytes = 0
            scan_label = ""
        absorbed = 0
        pr_slash_fwd = root_path + "/"
        pr_slash_bwd = root_path + "\\"
        for fparent in folders_by_scan_paths.get(sid, ()):
            if fparent == root_path:
                continue
            if not (fparent.startswith(pr_slash_fwd)
                    or fparent.startswith(pr_slash_bwd)):
                continue
            ck = (sid, fparent)
            if ck in project_keys or ck in inside_marker:
                continue
            cd = folders[ck]
            tot_files += cd["count"]
            tot_bytes += cd["total_bytes"]
            absorbed += 1
            if not scan_label:
                scan_label = cd["scan_label"]
        media_root_data[root_key] = {
            "label":       label,
            "dominance":   dom,
            "files":       tot_files,
            "bytes":       tot_bytes,
            "absorbed":    absorbed,
            "scan_label":  scan_label,
            "sid":         sid,
        }

    # Step 6: leaves whose rollup root is an ancestor (not themselves)
    # are absorbed and won't surface as their own row.
    for leaf_key, root_key in rollup_root.items():
        if root_key != leaf_key:
            media_absorbed.add(leaf_key)

    # ── Build final result list.
    results: list[dict] = []
    emitted_media_roots: set[tuple[int, str]] = set()
    for key, d in folders.items():
        sid, parent = key
        # Suppress folders inside a known marker tree (the project root
        # surfaces instead). Project roots themselves are not in
        # `inside_marker` because the parent path doesn't contain the
        # marker segment.
        if key in inside_marker and key not in project_keys:
            continue
        if key in descendant_of_project:
            continue
        if key in media_absorbed:
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
        elif key in media_root_data:
            info = media_root_data[key]
            category    = info["label"]
            dominance   = info["dominance"]
            file_count  = info["files"]
            total_bytes = info["bytes"]
            subcategory = (f"+{info['absorbed']} subfolders"
                           if info["absorbed"] else "")
            emitted_media_roots.add(key)
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

    # Emit promoted-ancestor rows that weren't visited by the main loop
    # because the folder has no direct files (e.g. a device-backup folder
    # whose children are DCIM/, Pictures/, etc.).
    for root_key, info in media_root_data.items():
        if root_key in emitted_media_roots:
            continue
        if root_key in folders:
            continue
        if info["files"] < min_files:
            continue
        sid, parent = root_key
        results.append({
            "scan_id":     sid,
            "scan_label":  info["scan_label"],
            "folder":      parent,
            "category":    info["label"],
            "subcategory": (f"+{info['absorbed']} subfolders"
                            if info["absorbed"] else ""),
            "file_count":  info["files"],
            "total_bytes": info["bytes"],
            "dominance":   round(info["dominance"], 3),
        })

    results = group_backup_copies(results)

    # Sort by category-display-order then size desc.
    cat_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    results.sort(key=lambda r: (cat_rank.get(r["category"], len(CATEGORY_ORDER)),
                                -r["total_bytes"]))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Cross-drive backup grouping.

_MIRROR_SUFFIX_DEPTH = 4
_MIRROR_BYTES_TOLERANCE = 0.05


def _trailing_suffix_key(folder: str, depth: int = _MIRROR_SUFFIX_DEPTH) -> str:
    parts = [p for p in _split_segments(folder) if p]
    tail = parts[-depth:]
    return "/".join(s.strip().lower() for s in tail)


def group_backup_copies(
    results: list[dict],
    suffix_depth: int = _MIRROR_SUFFIX_DEPTH,
    bytes_tolerance: float = _MIRROR_BYTES_TOLERANCE,
) -> list[dict]:
    """Collapse rows that look like backup copies of the same folder living
    on different drives. Two rows group when they share the same category,
    the same trailing N path segments, and have total_bytes within ±tol of
    each other. Within a group, the row with the highest file_count becomes
    the *primary* and carries the others under `mirrors`.
    """
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        key = (r["category"], _trailing_suffix_key(r["folder"], suffix_depth))
        buckets[key].append(idx)

    absorbed: set[int] = set()
    for indices in buckets.values():
        if len(indices) < 2:
            continue
        rows = sorted(
            ((i, results[i]) for i in indices),
            key=lambda t: (-t[1]["file_count"], -t[1]["total_bytes"]),
        )
        primary_idx, primary = rows[0]
        primary_bytes = primary["total_bytes"] or 1
        mirrors: list[dict] = []
        for idx, r in rows[1:]:
            delta = abs(r["total_bytes"] - primary["total_bytes"]) / primary_bytes
            if delta > bytes_tolerance:
                continue
            mirrors.append({
                "folder":      r["folder"],
                "scan_id":     r["scan_id"],
                "scan_label":  r["scan_label"],
                "file_count":  r["file_count"],
                "total_bytes": r["total_bytes"],
                "files_delta": r["file_count"] - primary["file_count"],
            })
            absorbed.add(idx)
        if mirrors:
            primary["mirrors"] = mirrors
            primary["mirror_count"] = len(mirrors)
            primary["has_mirrors"] = True

    return [r for i, r in enumerate(results) if i not in absorbed]

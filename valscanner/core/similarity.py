from __future__ import annotations
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from .db import repo_for
from .filters import file_is_skipped, path_has_skipped_dir


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot  = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    magA = math.sqrt(sum(v * v for v in a.values())) or 1
    magB = math.sqrt(sum(v * v for v in b.values())) or 1
    return dot / (magA * magB)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _size_sim(s1: int, s2: int) -> float:
    lo, hi = min(s1, s2), max(s1, s2)
    return lo / hi if hi else 1.0


def _strict_subpath(child: str, parent: str) -> bool:
    cp, pp = Path(child), Path(parent)
    if cp == pp:
        return False
    try:
        cp.relative_to(pp)
        return True
    except ValueError:
        return False


def _compute_folder_data_and_pairs(
    db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
):
    repo = repo_for(db_path)
    rows = repo.iter_similarity_rows(scan_ids=scan_ids)

    fopts = filters or {}
    apply_filters = any(fopts.get(k) for k in (
        "skip_hidden_files", "skip_hidden_dirs", "skip_system", "skip_caches",
        "skip_vcs", "skip_binaries", "skip_temp", "skip_logs",
    ))

    folder_data: dict = defaultdict(lambda: {
        "names": set(), "exts": Counter(), "hashes": set(),
        "total_bytes": 0, "count": 0, "scan_id": 0, "scan_label": "",
    })
    for r in rows:
        if apply_filters:
            ext = (r["extension"] or "").lower()
            if ext.startswith("(") or ext == "":
                ext = ""
            if file_is_skipped(r["filename"] or "", ext, fopts):
                continue
            if path_has_skipped_dir(r["path"], fopts):
                continue
        parent = str(Path(r["path"]).parent)
        key    = (r["scan_id"], parent)
        d      = folder_data[key]
        d["scan_id"]    = r["scan_id"]
        d["scan_label"] = r["scan_label"]
        d["names"].add(r["norm_name"])
        d["exts"][r["extension"]] += 1
        if r["sha256"]:
            d["hashes"].add(r["sha256"])
        d["total_bytes"] += r["size_bytes"] or 0
        d["count"]       += 1

    folders    = [((sid, p), d) for (sid, p), d in folder_data.items() if d["count"] >= min_files]
    has_hashes = any(d["hashes"] for _, d in folders)

    def _make_pair(keyA, dA, keyB, dB):
        sidA, pA   = keyA
        sidB, pB   = keyB
        name_score = _jaccard(dA["names"], dB["names"])
        size_score = _size_sim(dA["total_bytes"], dB["total_bytes"])
        ext_score  = _cosine(dict(dA["exts"]), dict(dB["exts"]))
        hash_score = _jaccard(dA["hashes"], dB["hashes"]) if has_hashes else 0.0
        if has_hashes:
            score = name_score * 0.40 + size_score * 0.15 + ext_score * 0.20 + hash_score * 0.25
        else:
            score = name_score * 0.52 + size_score * 0.18 + ext_score * 0.30
        if score < threshold:
            return None
        sim_label = (
            "near-identical" if score >= 0.90 else
            "highly similar" if score >= 0.70 else
            "similar"        if score >= 0.55 else "possibly related"
        )
        return {
            "folder_a":      pA,
            "folder_b":      pB,
            "scan_id_a":     sidA,
            "scan_id_b":     sidB,
            "scan_label_a":  dA["scan_label"],
            "scan_label_b":  dB["scan_label"],
            "score":         round(score, 4),
            "label":         sim_label,
            "name_score":    round(name_score, 3),
            "size_score":    round(size_score, 3),
            "ext_score":     round(ext_score, 3),
            "hash_score":    round(hash_score, 3),
            "files_a":       dA["count"],
            "files_b":       dB["count"],
            "bytes_a":       dA["total_bytes"],
            "bytes_b":       dB["total_bytes"],
            "shared_names":  len(dA["names"] & dB["names"]),
            "shared_hashes": len(dA["hashes"] & dB["hashes"]),
            "children":      [],
        }

    all_pairs = []
    n = len(folders)
    for i in range(n):
        if stop_flag and stop_flag():
            break
        if progress_cb:
            progress_cb(i, n)
        for j in range(i + 1, n):
            if stop_flag and stop_flag():
                break
            p = _make_pair(folders[i][0], folders[i][1], folders[j][0], folders[j][1])
            if p:
                all_pairs.append(p)
    if progress_cb:
        progress_cb(n, n)
    return folder_data, all_pairs


def find_similar_folders(
    db_path: str,
    min_files: int = 3,
    threshold: float = 0.40,
    max_results: int = 200,
    scan_ids: list | None = None,
    filters: dict | None = None,
    stop_flag: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list:
    _, all_pairs = _compute_folder_data_and_pairs(
        db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
    )

    def _depth(r):
        return len(Path(r["folder_a"]).parts) + len(Path(r["folder_b"]).parts)
    all_pairs.sort(key=lambda r: (_depth(r), -r["score"]))

    top_level: list = []
    child_set: set  = set()
    for pair in all_pairs:
        if stop_flag and stop_flag():
            break
        pid = id(pair)
        if pid in child_set:
            continue
        cA, cB   = pair["folder_a"], pair["folder_b"]
        csA, csB = pair["scan_id_a"], pair["scan_id_b"]
        placed   = False
        for top in top_level:
            tA, tB   = top["folder_a"], top["folder_b"]
            tsA, tsB = top["scan_id_a"], top["scan_id_b"]
            if ((csA == tsA and csB == tsB and
                 _strict_subpath(cA, tA) and _strict_subpath(cB, tB)) or
                (csA == tsB and csB == tsA and
                 _strict_subpath(cA, tB) and _strict_subpath(cB, tA))):
                top["children"].append(pair)
                child_set.add(pid)
                placed = True
                break
        if not placed:
            top_level.append(pair)

    top_level.sort(key=lambda r: r["score"], reverse=True)
    for t in top_level:
        t["children"].sort(key=lambda r: r["score"], reverse=True)
    return top_level[:max_results]


def find_similar_groups(
    db_path: str,
    min_files: int = 3,
    threshold: float = 0.40,
    max_results: int = 200,
    scan_ids: list | None = None,
    filters: dict | None = None,
    stop_flag: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list:
    folder_data, all_pairs = _compute_folder_data_and_pairs(
        db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
    )

    parent: dict = {}

    def _root(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    def _union(a, b):
        ra, rb = _root(a), _root(b)
        if ra != rb:
            parent[ra] = rb

    for p in all_pairs:
        ka = (p["scan_id_a"], p["folder_a"])
        kb = (p["scan_id_b"], p["folder_b"])
        for k in (ka, kb):
            if k not in parent:
                parent[k] = k
        _union(ka, kb)

    components: dict = defaultdict(list)
    for k in parent:
        components[_root(k)].append(k)

    groups: list = []
    for keys in components.values():
        if len(keys) < 2:
            continue
        kset = set(keys)
        gedges = [
            p for p in all_pairs
            if (p["scan_id_a"], p["folder_a"]) in kset
            and (p["scan_id_b"], p["folder_b"]) in kset
        ]
        if not gedges:
            continue
        m_data = [folder_data[k] for k in keys]
        shared_names  = set.intersection(*[d["names"]  for d in m_data]) if m_data else set()
        any_hashes    = any(d["hashes"] for d in m_data)
        shared_hashes = set.intersection(*[d["hashes"] for d in m_data]) if any_hashes else set()

        n_edges = len(gedges)
        avg_score = sum(p["score"]      for p in gedges) / n_edges
        avg_name  = sum(p["name_score"] for p in gedges) / n_edges
        avg_size  = sum(p["size_score"] for p in gedges) / n_edges
        avg_ext   = sum(p["ext_score"]  for p in gedges) / n_edges
        avg_hash  = sum(p["hash_score"] for p in gedges) / n_edges
        label = (
            "near-identical" if avg_score >= 0.90 else
            "highly similar" if avg_score >= 0.70 else
            "similar"        if avg_score >= 0.55 else "possibly related"
        )

        members = []
        total_bytes = total_files = 0
        for (sid, path), d in zip(keys, m_data):
            members.append({
                "folder":     path,
                "scan_id":    sid,
                "scan_label": d["scan_label"],
                "files":      d["count"],
                "bytes":      d["total_bytes"],
            })
            total_bytes += d["total_bytes"]
            total_files += d["count"]
        members.sort(key=lambda m: m["folder"])

        groups.append({
            "members":       members,
            "size":          len(members),
            "score":         round(avg_score, 4),
            "max_score":     round(max(p["score"] for p in gedges), 4),
            "min_score":     round(min(p["score"] for p in gedges), 4),
            "edges_count":   n_edges,
            "label":         label,
            "name_score":    round(avg_name, 3),
            "size_score":    round(avg_size, 3),
            "ext_score":     round(avg_ext, 3),
            "hash_score":    round(avg_hash, 3),
            "shared_names":  len(shared_names),
            "shared_hashes": len(shared_hashes),
            "total_bytes":   total_bytes,
            "total_files":   total_files,
            "children":      [],
        })

    def _group_depth(g):
        return sum(len(Path(m["folder"]).parts) for m in g["members"])
    groups.sort(key=lambda g: (_group_depth(g), -g["score"]))

    def _is_child_group(child, parent_g):
        parent_members = [(m["scan_id"], m["folder"]) for m in parent_g["members"]]
        for cm in child["members"]:
            ok = False
            for psid, ppath in parent_members:
                if cm["scan_id"] == psid and _strict_subpath(cm["folder"], ppath):
                    ok = True
                    break
            if not ok:
                return False
        return True

    top_level: list = []
    child_set: set  = set()
    for g in groups:
        if stop_flag and stop_flag():
            break
        gid = id(g)
        if gid in child_set:
            continue
        placed = False
        for top in top_level:
            if _is_child_group(g, top):
                top["children"].append(g)
                child_set.add(gid)
                placed = True
                break
        if not placed:
            top_level.append(g)

    top_level.sort(key=lambda g: g["score"], reverse=True)
    for t in top_level:
        t["children"].sort(key=lambda g: g["score"], reverse=True)
    return top_level[:max_results]


def normalize_to_group(r: dict) -> dict:
    """Convert a legacy pair-shape result to the new group-shape, recursively."""
    if "members" in r:
        return r
    members = [
        {
            "folder":     r.get("folder_a", ""),
            "scan_id":    r.get("scan_id_a", 0),
            "scan_label": r.get("scan_label_a", ""),
            "files":      r.get("files_a", 0),
            "bytes":      r.get("bytes_a", 0),
        },
        {
            "folder":     r.get("folder_b", ""),
            "scan_id":    r.get("scan_id_b", 0),
            "scan_label": r.get("scan_label_b", ""),
            "files":      r.get("files_b", 0),
            "bytes":      r.get("bytes_b", 0),
        },
    ]
    return {
        "members":       members,
        "size":          2,
        "score":         r.get("score", 0.0),
        "max_score":     r.get("score", 0.0),
        "min_score":     r.get("score", 0.0),
        "edges_count":   1,
        "label":         r.get("label", "similar"),
        "name_score":    r.get("name_score", 0.0),
        "size_score":    r.get("size_score", 0.0),
        "ext_score":     r.get("ext_score", 0.0),
        "hash_score":    r.get("hash_score", 0.0),
        "shared_names":  r.get("shared_names", 0),
        "shared_hashes": r.get("shared_hashes", 0),
        "total_bytes":   r.get("bytes_a", 0) + r.get("bytes_b", 0),
        "total_files":   r.get("files_a", 0) + r.get("files_b", 0),
        "children":      [normalize_to_group(c) for c in r.get("children", [])],
    }

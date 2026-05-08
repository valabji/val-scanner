from __future__ import annotations
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


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


def find_similar_folders(
    db_path: str,
    min_files: int = 3,
    threshold: float = 0.40,
    max_results: int = 200,
    scan_ids: list | None = None,
) -> list:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    base_q = (
        "SELECT f.scan_id, COALESCE(NULLIF(s.label,''), s.root) AS scan_label, "
        "       f.path, f.extension, f.size_bytes, f.sha256, "
        "       LOWER(REPLACE(REPLACE(f.filename,' ',''),'_','')) AS norm_name "
        "FROM files f JOIN scans s ON s.id = f.scan_id"
    )
    if scan_ids:
        placeholders = ",".join("?" * len(scan_ids))
        rows = conn.execute(base_q + f" WHERE f.scan_id IN ({placeholders})", scan_ids).fetchall()
    else:
        rows = conn.execute(base_q).fetchall()
    conn.close()

    folder_data: dict = defaultdict(lambda: {
        "names": set(), "exts": Counter(), "hashes": set(),
        "total_bytes": 0, "count": 0, "scan_id": 0, "scan_label": "",
    })
    for r in rows:
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
        for j in range(i + 1, n):
            p = _make_pair(folders[i][0], folders[i][1], folders[j][0], folders[j][1])
            if p:
                all_pairs.append(p)

    def _depth(r):
        return len(Path(r["folder_a"]).parts) + len(Path(r["folder_b"]).parts)
    all_pairs.sort(key=lambda r: (_depth(r), -r["score"]))

    def _is_strict_subpath(child: str, parent: str) -> bool:
        cp = Path(child)
        pp = Path(parent)
        if cp == pp:
            return False
        try:
            cp.relative_to(pp)
            return True
        except ValueError:
            return False

    top_level: list = []
    child_set: set  = set()

    for pair in all_pairs:
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
                 _is_strict_subpath(cA, tA) and _is_strict_subpath(cB, tB)) or
                (csA == tsB and csB == tsA and
                 _is_strict_subpath(cA, tB) and _is_strict_subpath(cB, tA))):
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

from __future__ import annotations
import logging
import math
import multiprocessing as _mp
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)

# Hard ceiling on worker processes. Each spawned worker re-pickles the full
# folders list, so on 32+ core boxes uncapped scaling can OOM the host.
_MAX_WORKERS_HARD_CAP = 8

from .db import repo_for
from .filters import file_is_skipped, path_has_skipped_dir


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    # iterate the smaller dict for the dot product
    if len(a) > len(b):
        a, b = b, a
    b_get = b.get
    dot = 0
    for k, v in a.items():
        ov = b_get(k)
        if ov:
            dot += v * ov
    if not dot:
        return 0.0
    magA = math.sqrt(sum(v * v for v in a.values())) or 1
    magB = math.sqrt(sum(v * v for v in b.values())) or 1
    return dot / (magA * magB)


def _cosine_pre(a: dict, ma: float, b: dict, mb: float) -> float:
    """Cosine with precomputed magnitudes; iterates the smaller dict."""
    if not a or not b or ma == 0.0 or mb == 0.0:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    b_get = b.get
    dot = 0
    for k, v in a.items():
        ov = b_get(k)
        if ov:
            dot += v * ov
    return dot / (ma * mb) if dot else 0.0


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    if not inter:
        return 0.0
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def _jaccard_pre(a: set, la: int, b: set, lb: int) -> float:
    """Jaccard with precomputed cardinalities; iterates the smaller set."""
    if la == 0 and lb == 0:
        return 1.0
    if la == 0 or lb == 0:
        return 0.0
    if la > lb:
        a, la, b, lb = b, lb, a, la
    inter = sum(1 for x in a if x in b)
    if not inter:
        return 0.0
    return inter / (la + lb - inter)


def _size_sim(s1: int, s2: int) -> float:
    if s1 == s2:
        return 1.0 if s1 else 1.0
    if s1 < s2:
        lo, hi = s1, s2
    else:
        lo, hi = s2, s1
    return lo / hi if hi else 1.0


def _strict_subpath(child: str, parent: str) -> bool:
    if child == parent:
        return False
    # Fast path: pure string compare. Falls back to Path semantics if the
    # cheap test is ambiguous (e.g. trailing separators, normalization).
    if parent and (child.startswith(parent + '/') or child.startswith(parent + '\\')):
        return True
    cp, pp = Path(child), Path(parent)
    if cp == pp:
        return False
    try:
        cp.relative_to(pp)
        return True
    except ValueError:
        return False


def _score_pair(keyA, dA, keyB, dB, has_hashes, threshold):
    """Score a single folder pair. Returns a pair dict or None if below threshold.

    Module-level so it's importable from worker processes spawned by
    ProcessPoolExecutor.
    """
    sidA, pA   = keyA
    sidB, pB   = keyB
    name_score = _jaccard_pre(dA["names"], dA["_names_n"], dB["names"], dB["_names_n"])
    size_score = _size_sim(dA["total_bytes"], dB["total_bytes"])
    ext_score  = _cosine_pre(dA["_exts_d"], dA["_exts_mag"],
                             dB["_exts_d"], dB["_exts_mag"])
    hash_score = (
        _jaccard_pre(dA["hashes"], dA["_hashes_n"], dB["hashes"], dB["_hashes_n"])
        if has_hashes else 0.0
    )
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


# Worker-process module-level state, populated by _init_worker_state via
# ProcessPoolExecutor's initializer. Avoids re-pickling the folder list per task.
_W_FOLDERS: list | None = None
_W_HAS_HASHES: bool      = False
_W_THRESHOLD: float      = 0.0


def _init_worker_state(folders, has_hashes, threshold):
    global _W_FOLDERS, _W_HAS_HASHES, _W_THRESHOLD
    _W_FOLDERS    = folders
    _W_HAS_HASHES = has_hashes
    _W_THRESHOLD  = threshold


def _score_candidate_chunk(chunk):
    folders   = _W_FOLDERS
    has_hash  = _W_HAS_HASHES
    threshold = _W_THRESHOLD
    out = []
    out_append = out.append
    for i, j in chunk:
        keyA, dA = folders[i]
        keyB, dB = folders[j]
        p = _score_pair(keyA, dA, keyB, dB, has_hash, threshold)
        if p is not None:
            out_append(p)
    return out


def _score_full_chunk(chunk_args):
    """Score all (i, j) with i in [i_start, i_end) and j > i. Used for fallback path."""
    i_start, i_end = chunk_args
    folders   = _W_FOLDERS
    has_hash  = _W_HAS_HASHES
    threshold = _W_THRESHOLD
    n = len(folders)
    out = []
    out_append = out.append
    for i in range(i_start, i_end):
        keyA, dA = folders[i]
        for j in range(i + 1, n):
            keyB, dB = folders[j]
            p = _score_pair(keyA, dA, keyB, dB, has_hash, threshold)
            if p is not None:
                out_append(p)
    return out


# Hard cap on the candidate set to keep main-process memory bounded. Each
# (i,j) tuple plus set overhead is ~120 bytes, so 5M ≈ 600MB. Past this we
# bail out to the full O(n²) scoring path (which holds no candidate set).
_MAX_CANDIDATES = 5_000_000


def _generate_candidates(folders, has_hashes, threshold):
    """Return a list of (i, j) candidate pairs using inverted indexes, or None
    if the threshold is too low to safely prune OR if pruning would blow past
    the memory cap (caller runs full O(n²) in that case).

    Weights — has_hashes: name 0.40, size 0.15, ext 0.20, hash 0.25
              no_hashes:  name 0.52, size 0.18, ext 0.30
    A pair sharing zero names AND zero hashes AND zero extensions has
    name=ext=hash=0, so max score = size_weight. Any pair scoring ≥ threshold
    must share at least one of these. We index whichever subset is needed
    given the threshold cut-off.
    """
    use_ext: bool
    if has_hashes:
        # ext-only contribution max = ext + size = 0.35
        use_ext = threshold <= 0.35
    else:
        # ext-only contribution max = ext + size = 0.48
        use_ext = threshold <= 0.48

    # Safety net: if even (name OR hash OR ext) pruning is unsafe — i.e. a pair
    # sharing zero of all three could still pass — fall back. This only happens
    # at very low thresholds (≤ size_weight).
    size_w = 0.15 if has_hashes else 0.18
    if threshold <= size_w:
        return None

    n = len(folders)
    # Skip emission from buckets shared by near-universal tokens (e.g. .DS_Store,
    # Thumbs.db, README.md). Their m*(m-1)/2 pairs are noise — folders that
    # share *only* such common tokens score below threshold anyway, and folders
    # that are genuinely similar share many tokens and will still be emitted
    # from the discriminative buckets. The cutoff stays generous so true
    # bulk-duplicates (e.g. two scans of the same tree) remain detectable
    # through their unique-ish tokens.
    big_bucket = max(1000, n // 2)

    name_to_idx: dict[str, list[int]] = defaultdict(list)
    hash_to_idx: dict[str, list[int]] = defaultdict(list) if has_hashes else {}
    ext_to_idx:  dict[str, list[int]] = defaultdict(list) if use_ext else {}

    for i, (_, d) in enumerate(folders):
        for nm in d["names"]:
            name_to_idx[nm].append(i)
        if has_hashes:
            for h in d["hashes"]:
                hash_to_idx[h].append(i)
        if use_ext:
            for e in d["_exts_d"]:
                ext_to_idx[e].append(i)

    candidates: set = set()
    cand_add = candidates.add
    overflow = False

    def _emit(idxs: list[int]) -> bool:
        m = len(idxs)
        for a in range(m):
            ia = idxs[a]
            for b in range(a + 1, m):
                cand_add((ia, idxs[b]))
                if len(candidates) > _MAX_CANDIDATES:
                    return True
        return False

    skipped_buckets = 0
    for idxs in name_to_idx.values():
        m = len(idxs)
        if m < 2:
            continue
        if m > big_bucket:
            skipped_buckets += 1
            continue
        if _emit(idxs):
            overflow = True
            break
    if not overflow and has_hashes:
        for idxs in hash_to_idx.values():
            m = len(idxs)
            if m < 2:
                continue
            if m > big_bucket:
                skipped_buckets += 1
                continue
            if _emit(idxs):
                overflow = True
                break
    if not overflow and use_ext:
        for idxs in ext_to_idx.values():
            m = len(idxs)
            if m < 2:
                continue
            if m > big_bucket:
                skipped_buckets += 1
                continue
            if _emit(idxs):
                overflow = True
                break

    if overflow:
        _log.warning(
            "similarity: candidate set exceeded %d pairs — falling back to "
            "full O(n²) scoring (lower-memory path)", _MAX_CANDIDATES,
        )
        return None
    if skipped_buckets:
        _log.info(
            "similarity: skipped %d common-token bucket(s) "
            "(folders/bucket > %d) for memory safety",
            skipped_buckets, big_bucket,
        )
    return candidates


def _resolve_workers(workers: int | None) -> int:
    if workers is None or workers <= 0:
        n = max(1, (os.cpu_count() or 1))
    else:
        n = max(1, int(workers))
    return min(n, _MAX_WORKERS_HARD_CAP)


def _compute_folder_data_and_pairs(
    db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
    workers: int | None = 1,
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
            if path_has_skipped_dir(r["path"], fopts, root=r.get("scan_root")):
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
    n = len(folders)

    # Precompute once per folder: cardinalities and ext-vector magnitudes.
    for _, d in folders:
        exts_dict = dict(d["exts"])
        d["_exts_d"]   = exts_dict
        d["_exts_mag"] = math.sqrt(sum(v * v for v in exts_dict.values()))
        d["_names_n"]  = len(d["names"])
        d["_hashes_n"] = len(d["hashes"])

    n_workers = _resolve_workers(workers)

    # Candidate generation: inverted-index prune by shared name / hash / ext.
    # Returns None at very low thresholds where pruning isn't safe.
    candidates = _generate_candidates(folders, has_hashes, threshold) if n >= 2 else set()

    all_pairs = _score_pairs(
        folders, candidates, has_hashes, threshold,
        n_workers, stop_flag, progress_cb,
    )
    return folder_data, all_pairs


# Process-pool overhead (spawn + pickle init) only pays off at this many pair
# evaluations. Below the bar, run sequentially in-process.
_PARALLEL_MIN_WORK = 20_000

# Above this many tokens (names + hashes + exts) across all folders, pickling
# the folder list to each worker becomes expensive enough to risk OOM in the
# aggregate (main + N workers each hold a full copy). Force sequential.
_PARALLEL_MAX_TOKENS = 4_000_000


def _folders_token_estimate(folders) -> int:
    total = 0
    for _, d in folders:
        total += d["_names_n"] + d["_hashes_n"] + len(d["_exts_d"])
    return total


def _score_pairs(folders, candidates, has_hashes, threshold,
                 n_workers, stop_flag, progress_cb):
    n = len(folders)

    if candidates is None:
        # Full O(n²) fallback (very low threshold).
        return _score_full(folders, has_hashes, threshold,
                           n_workers, stop_flag, progress_cb)

    cand_list = list(candidates)
    total = len(cand_list)

    if total == 0:
        if progress_cb:
            progress_cb(0, 0)
        return []

    # Sequential when pool overhead would dominate, or when shipping `folders`
    # to N workers would risk OOM.
    if n_workers <= 1 or total < _PARALLEL_MIN_WORK:
        return _score_candidates_sequential(
            folders, cand_list, has_hashes, threshold, stop_flag, progress_cb,
        )
    tokens = _folders_token_estimate(folders)
    if tokens > _PARALLEL_MAX_TOKENS:
        _log.info(
            "similarity: folder dataset large (%d tokens) — running scoring "
            "sequentially to keep memory bounded", tokens,
        )
        return _score_candidates_sequential(
            folders, cand_list, has_hashes, threshold, stop_flag, progress_cb,
        )

    return _score_candidates_parallel(
        folders, cand_list, has_hashes, threshold,
        n_workers, stop_flag, progress_cb,
    )


def _score_candidates_sequential(folders, cand_list, has_hashes, threshold,
                                 stop_flag, progress_cb):
    total = len(cand_list)
    out = []
    out_append = out.append
    # Throttle progress + stop-flag checks to once every 4096 pairs.
    check_mask = 4095
    for k, (i, j) in enumerate(cand_list):
        if k & check_mask == 0:
            if stop_flag and stop_flag():
                break
            if progress_cb:
                progress_cb(k, total)
        keyA, dA = folders[i]
        keyB, dB = folders[j]
        p = _score_pair(keyA, dA, keyB, dB, has_hashes, threshold)
        if p is not None:
            out_append(p)
    if progress_cb:
        progress_cb(total, total)
    return out


def _score_candidates_parallel(folders, cand_list, has_hashes, threshold,
                               n_workers, stop_flag, progress_cb):
    total = len(cand_list)
    # ~8 chunks per worker for load balancing; minimum chunk size to amortize IPC.
    chunk_size = max(2_000, total // (n_workers * 8))
    chunks = [cand_list[i:i + chunk_size] for i in range(0, total, chunk_size)]
    # Don't spawn more workers than chunks — extra processes pay pickle cost for
    # no work.
    n_workers = max(1, min(n_workers, len(chunks)))

    all_pairs: list = []
    ex = None
    try:
        # Pin to "spawn" so behaviour matches across macOS / Windows / Linux and
        # never inherits a forked Qt event loop.
        ctx = _mp.get_context("spawn")
        ex = ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_init_worker_state,
            initargs=(folders, has_hashes, threshold),
            mp_context=ctx,
        )
        futures = [ex.submit(_score_candidate_chunk, c) for c in chunks]
        done = 0
        chunks_total = len(chunks)
        stopped = False
        for fut in as_completed(futures):
            if stop_flag and stop_flag():
                stopped = True
                break
            all_pairs.extend(fut.result())
            done += 1
            if progress_cb:
                progress_cb(int(done * total / chunks_total), total)
        if stopped:
            ex.shutdown(wait=False, cancel_futures=True)
        else:
            ex.shutdown(wait=True)
    except (BrokenProcessPool, OSError, MemoryError, RuntimeError) as exc:
        # Multiprocessing unavailable (frozen build, restricted env, OOM, …) —
        # fall back to sequential so the analysis still completes.
        _log.warning("similarity: parallel scoring failed (%s); falling back to sequential", exc)
        if ex is not None:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        return _score_candidates_sequential(
            folders, cand_list, has_hashes, threshold, stop_flag, progress_cb,
        )

    if progress_cb:
        progress_cb(total, total)
    return all_pairs


def _score_full(folders, has_hashes, threshold,
                n_workers, stop_flag, progress_cb):
    n = len(folders)
    total_work = n * (n - 1) // 2

    if n_workers <= 1 or total_work < _PARALLEL_MIN_WORK:
        return _score_full_sequential(folders, has_hashes, threshold,
                                      stop_flag, progress_cb)

    if _folders_token_estimate(folders) > _PARALLEL_MAX_TOKENS:
        _log.info(
            "similarity: folder dataset large — running full scan "
            "sequentially to keep memory bounded",
        )
        return _score_full_sequential(folders, has_hashes, threshold,
                                      stop_flag, progress_cb)

    # Carve the i-axis into balanced ranges. Lower i has more inner work
    # (triangle of width n-i-1), so use cumulative-work splits.
    target = total_work / max(1, n_workers * 4)
    chunks: list[tuple[int, int]] = []
    i = 0
    acc = 0
    last = 0
    while i < n:
        acc += (n - i - 1)
        if acc >= target or i == n - 1:
            chunks.append((last, i + 1))
            last = i + 1
            acc = 0
        i += 1

    # Don't spawn more workers than chunks.
    n_workers = max(1, min(n_workers, len(chunks)))

    all_pairs: list = []
    ex = None
    try:
        ctx = _mp.get_context("spawn")
        ex = ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_init_worker_state,
            initargs=(folders, has_hashes, threshold),
            mp_context=ctx,
        )
        futures = [ex.submit(_score_full_chunk, c) for c in chunks]
        done = 0
        chunks_total = len(chunks)
        stopped = False
        for fut in as_completed(futures):
            if stop_flag and stop_flag():
                stopped = True
                break
            all_pairs.extend(fut.result())
            done += 1
            if progress_cb:
                progress_cb(int(done * n / chunks_total), n)
        if stopped:
            ex.shutdown(wait=False, cancel_futures=True)
        else:
            ex.shutdown(wait=True)
    except (BrokenProcessPool, OSError, MemoryError, RuntimeError) as exc:
        _log.warning("similarity: parallel full-scan failed (%s); falling back to sequential", exc)
        if ex is not None:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        return _score_full_sequential(folders, has_hashes, threshold,
                                      stop_flag, progress_cb)

    if progress_cb:
        progress_cb(n, n)
    return all_pairs


def _score_full_sequential(folders, has_hashes, threshold,
                           stop_flag, progress_cb):
    n = len(folders)
    out: list = []
    out_append = out.append
    for i in range(n):
        if stop_flag and stop_flag():
            break
        if progress_cb:
            progress_cb(i, n)
        keyA, dA = folders[i]
        for j in range(i + 1, n):
            keyB, dB = folders[j]
            p = _score_pair(keyA, dA, keyB, dB, has_hashes, threshold)
            if p is not None:
                out_append(p)
    if progress_cb:
        progress_cb(n, n)
    return out


def find_similar_folders(
    db_path: str,
    min_files: int = 3,
    threshold: float = 0.40,
    max_results: int = 200,
    scan_ids: list | None = None,
    filters: dict | None = None,
    stop_flag: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    workers: int | None = 1,
) -> list:
    _, all_pairs = _compute_folder_data_and_pairs(
        db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
        workers=workers,
    )

    # Fast depth approximation: counting path separators is equivalent for
    # ordering purposes and avoids per-pair Path() construction.
    def _depth(r):
        a = r["folder_a"]
        b = r["folder_b"]
        return a.count('/') + a.count('\\') + b.count('/') + b.count('\\')
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
    workers: int | None = 1,
) -> list:
    folder_data, all_pairs = _compute_folder_data_and_pairs(
        db_path, min_files, threshold, scan_ids, filters, stop_flag, progress_cb,
        workers=workers,
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
        total = 0
        for m in g["members"]:
            f = m["folder"]
            total += f.count('/') + f.count('\\')
        return total
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

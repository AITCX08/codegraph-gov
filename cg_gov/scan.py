"""Orphan / duplicate scan.

Proactive complement to the on-write reuse check: instead of checking one intent at a time,
sweep the whole canonical index for (a) semantically near-duplicate symbol
clusters living in DIFFERENT files (wheels rebuilt) and (b) functions/methods
with zero internal callers (likely-dead reusable code, heuristic).

Reuses load_index (vecs/meta) and callers_counts -- no re-embedding here.
codegraph.db is read strictly read-only.
"""
import sys
import numpy as np

from .search import load_index
from .graph import callers_counts
from .db import get_connection

# Nested AI-tool mirror copies (.claude/.codex/.cursor worktree + skill mirrors)
# are excluded centrally in canonical.is_canonical(), so the index already drops
# them -- scan needs no local workaround.

# A cluster of same-named symbols whose embed text is byte-identical (avg_sim at
# the ceiling) is a NAME COLLISION (e.g. 232 def main(): in unrelated scripts),
# not a rebuilt wheel. Below this we call it a genuine reimplementation.
_NAME_COLLISION_SIM = 0.9999

# Names that are almost never genuinely orphaned even with 0 internal callers:
# framework/runtime entrypoints, lifecycle hooks, constructors, dunder methods.
_ENTRYPOINT_NAMES = {
    "main", "handler", "handle", "init", "setup", "teardown",
    "run", "start", "stop", "serve", "execute",
    "constructor", "render", "default",
}


class _UnionFind:
    """Minimal union-find over integer ids."""

    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _normalize(vecs: np.ndarray) -> np.ndarray:
    """L2-normalize rows once (float32, no full copy of the corpus norms)."""
    v = vecs.astype(np.float32, copy=False)
    norms = np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    return v / norms


def _avg_pair_sim(members_sorted, pair_sim):
    """Mean of MEASURED pairwise sims among the (capped) members, else None.

    M4: returns None when the capped subset shares no measured pair, rather than
    faking `threshold` as if it were a real measurement. Members are integer
    indices; pair_sim keys are ordered (i, j) tuples with i < j.
    """
    sims = [pair_sim[(a, b)]
            for ai, a in enumerate(members_sorted)
            for b in members_sorted[ai + 1:]
            if (a, b) in pair_sim]
    return round(float(np.mean(sims)), 4) if sims else None


def _classify(distinct_names: int, avg_sim):
    """name-collision = one shared name AND byte-identical embed text (sim ceiling);
    everything else (incl. unmeasured avg_sim=None, or same-name-but-not-identical
    like getConnection) is a genuine reimplementation."""
    if distinct_names == 1 and avg_sim is not None and avg_sim >= _NAME_COLLISION_SIM:
        return "name-collision"
    return "reimplementation"


def scan_duplicates(threshold: float = 0.86, max_per_cluster: int = 8,
                    block: int = 2000, progress=True, reimpl_only: bool = False):
    """Find clusters of semantically near-duplicate symbols across DIFFERENT files.

    Same-file overloads/co-located definitions are not duplication and are skipped.
    Memory-safe: never materializes the full N*N similarity matrix -- iterates
    row-blocks of `block` rows and only keeps the upper-triangle (j > i) cross-file
    pairs above `threshold`.

    Each cluster is classified:
      - "name-collision": all members share one name AND avg_sim is at the ceiling
        (byte-identical embed text, e.g. 232 unrelated `def main()`) -- noise.
      - "reimplementation": everything else, including same-named but non-identical
        clusters like getConnection (avg_sim 0.984) -- a real rebuilt wheel.
    reimplementation clusters sort ahead of name-collision ones. Pass
    `reimpl_only=True` to drop name-collision clusters entirely.

    Returns clusters as:
        [{"size": n, "avg_sim": x|None, "distinct_names": k, "category": str,
          "members": [{name,kind,abs_path,start_line,id}]}]
    avg_sim is None when the capped member subset shares no measured pair.
    """
    vecs, meta = load_index()
    norm = _normalize(vecs)
    n = norm.shape[0]
    paths = [m["abs_path"] for m in meta]

    # Collect surviving cross-file pairs (i, j, sim) with j > i.
    pair_i = []
    pair_j = []
    pair_s = []
    for start in range(0, n, block):
        end = min(start + block, n)
        sims = norm[start:end] @ norm.T  # (block, N)
        for local_row in range(end - start):
            i = start + local_row
            row = sims[local_row]
            # upper triangle only: candidate j must be > i
            cand = np.where(row[i + 1:] > threshold)[0]
            if cand.size == 0:
                continue
            cand += i + 1
            pi = paths[i]
            for j in cand:
                jj = int(j)
                if paths[jj] != pi:  # different file required
                    pair_i.append(i)
                    pair_j.append(jj)
                    pair_s.append(float(row[jj]))
        if progress:
            print(f"# scan_duplicates: {end}/{n} rows, {len(pair_i)} cross-file pairs",
                  file=sys.stderr)

    if not pair_i:
        return []

    # Union-Find the surviving pairs into clusters.
    uf = _UnionFind()
    for a, b in zip(pair_i, pair_j):
        uf.union(a, b)

    # Group members by root; accumulate per-node degree (#pairs touching it).
    members_by_root = {}
    degree = {}
    for a, b in zip(pair_i, pair_j):
        ra = uf.find(a)
        members_by_root.setdefault(ra, set()).update((a, b))
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1

    # Map (i, j) -> sim for avg computation (canonical ordered key).
    pair_sim = {}
    for a, b, s in zip(pair_i, pair_j, pair_s):
        pair_sim[(a, b)] = s

    clusters = []
    for root, member_set in members_by_root.items():
        members = list(member_set)
        if len(members) < 2:  # drop singletons (cannot occur, but be safe)
            continue
        # cap members at max_per_cluster, keep highest-degree nodes
        if len(members) > max_per_cluster:
            members = sorted(members, key=lambda x: degree.get(x, 0), reverse=True)[:max_per_cluster]
        members_sorted = sorted(members)
        avg_sim = _avg_pair_sim(members_sorted, pair_sim)
        cluster_members = [
            {
                "name": meta[idx]["name"],
                "kind": meta[idx]["kind"],
                "abs_path": meta[idx]["abs_path"],
                "start_line": meta[idx]["start_line"],
                "id": meta[idx]["id"],
            }
            for idx in members_sorted
        ]
        distinct_names = len({m["name"] for m in cluster_members})
        clusters.append({
            "size": len(cluster_members),
            "avg_sim": avg_sim,
            "distinct_names": distinct_names,
            "category": _classify(distinct_names, avg_sim),
            "members": cluster_members,
        })

    if reimpl_only:
        clusters = [c for c in clusters if c["category"] == "reimplementation"]

    # reimplementation (real signal) ahead of name-collision (noise); within each,
    # bigger clusters first, then higher avg_sim (None sorts last).
    def _key(c):
        cat_rank = 0 if c["category"] == "reimplementation" else 1
        sim = c["avg_sim"] if c["avg_sim"] is not None else -1.0
        return (cat_rank, -c["size"], -sim)

    clusters.sort(key=_key)
    return clusters


def _looks_like_entrypoint(name: str) -> bool:
    if not name:
        return True  # anonymous -> not a reusable named symbol, skip
    if name.startswith("__") and name.endswith("__"):
        return True  # dunder methods (__init__, __call__, ...)
    return name in _ENTRYPOINT_NAMES


def _is_exported(ids, con):
    """Fetch is_exported flag for given node ids (read-only). {id: bool}."""
    out = {}
    if not ids:
        return out
    # chunk the IN clause to stay well under SQLite's variable limit
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        placeholders = ",".join("?" * len(chunk))
        sql = f"SELECT id, is_exported FROM nodes WHERE id IN ({placeholders})"
        for r in con.execute(sql, tuple(chunk)):
            out[r["id"]] = bool(r["is_exported"])
    return out


def scan_orphans(con=None, limit: int = 200):
    """Find likely-dead reusable code: function/method symbols with 0 internal callers.

    HEURISTIC AND NOISY -- 0 internal callers does NOT mean dead. The symbol may be:
      - an HTTP route / RPC entry reached via the framework (not a 'calls' edge),
      - invoked via reflection / dynamic dispatch / string dispatch,
      - an exported public API consumed by another (uncrawled) service,
      - a CLI / lifecycle entrypoint.
    We exclude obvious entrypoints (main/handler/dunder/...), anonymous symbols,
    and is_exported public symbols, but the remainder still needs human judgement.

    Returns up to `limit` records sorted by abs_path:
        [{name, kind, abs_path, start_line, id, callers: 0}]
    """
    vecs, meta = load_index()
    candidates = [m for m in meta if m["kind"] in ("function", "method")]
    cand_ids = [m["id"] for m in candidates]

    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        counts = callers_counts(cand_ids, con=con)
        zero_ids = [m["id"] for m in candidates if counts.get(m["id"], 0) == 0]
        exported = _is_exported(zero_ids, con)
    finally:
        if close:
            con.close()

    orphans = []
    for m in candidates:
        if counts.get(m["id"], 0) != 0:
            continue
        if _looks_like_entrypoint(m["name"]):
            continue
        if exported.get(m["id"], False):  # exclude exported public API
            continue
        orphans.append({
            "name": m["name"],
            "kind": m["kind"],
            "abs_path": m["abs_path"],
            "start_line": m["start_line"],
            "id": m["id"],
            "callers": 0,
        })

    orphans.sort(key=lambda o: (o["abs_path"], o["start_line"]))
    return orphans[:limit]

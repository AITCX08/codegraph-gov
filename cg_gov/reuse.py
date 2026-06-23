from .db import get_connection
from .fts import fts_search
from .search import semantic_search
from .embed import LocalFastembed
from .fuse import rrf_merge
from .graph import callers_counts, get_symbols_by_ids
from .config import WORKSPACE_ROOT

WORKSPACE_PREFIX = str(WORKSPACE_ROOT).rstrip("/") + "/"
_SOURCE_NAME = {0: "fts", 1: "semantic"}


def _service_of(abs_path: str) -> str:
    if abs_path.startswith(WORKSPACE_PREFIX):
        return abs_path[len(WORKSPACE_PREFIX):].split("/", 1)[0] or "?"
    return "?"


def reuse_candidates(intent: str, k: int = 10, embedder=None, fetch: int = 30):
    """Union/rerank reuse search: fuse codegraph FTS (bm25) + local semantic (cosine) via RRF,
    enrich top-k with callers count + cross-repo distribution. Read-only."""
    embedder = embedder or LocalFastembed()
    fts_hits = fts_search(intent, limit=fetch)
    sem_hits = semantic_search(intent, embedder, k=fetch)
    fts_ids = [h["id"] for h in fts_hits]
    sem_ids = [h["id"] for h in sem_hits]
    fused = rrf_merge([fts_ids, sem_ids])[:k]
    ids = [i for i, _s, _src in fused]
    con = get_connection()
    try:
        info = get_symbols_by_ids(ids, con=con)
        counts = callers_counts(ids, con=con)
    finally:
        con.close()
    candidates = []
    service_distribution = {}
    for _id, score, srcs in fused:
        rec = info.get(_id, {"id": _id, "kind": "", "name": "", "qualified_name": "",
                             "signature": "", "abs_path": "", "start_line": 0})
        svc = _service_of(rec["abs_path"])
        service_distribution[svc] = service_distribution.get(svc, 0) + 1
        candidates.append({**rec, "rrf": round(score, 6), "callers": counts.get(_id, 0),
                           "sources": [_SOURCE_NAME[s] for s in srcs]})
    return {"candidates": candidates, "service_distribution": service_distribution}

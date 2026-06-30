from .db import get_connection
from .fts import fts_search
from .search import semantic_search
from .embed import LocalFastembed
from .fuse import rrf_merge_weighted
from .graph import callers_counts, get_symbols_by_ids
from .config import WORKSPACE_ROOT
from .query_expand import expand_intent

WORKSPACE_PREFIX = str(WORKSPACE_ROOT).rstrip("/") + "/"


def _service_of(abs_path: str) -> str:
    if abs_path.startswith(WORKSPACE_PREFIX):
        return abs_path[len(WORKSPACE_PREFIX):].split("/", 1)[0] or "?"
    return "?"


def reuse_candidates(intent: str, k: int = 10, embedder=None, fetch: int = 30):
    """Union/rerank reuse search over expanded query variants.

    Fuses codegraph FTS + local semantic search + optional low-weight markdown
    hints via weighted RRF, then enriches top-k with callers count and
    cross-repo distribution. Read-only.
    """
    embedder = embedder or LocalFastembed()
    expansion = expand_intent(intent)
    ranked_lists = []
    weights = []
    source_names = []
    for q in expansion["queries"]:
        if q["kind"] == "fts":
            hits = fts_search(q["text"], limit=fetch)
        else:
            hits = semantic_search(q["text"], embedder, k=fetch)
        ids = [h["id"] for h in hits if h.get("id")]
        if not ids:
            continue
        ranked_lists.append(ids)
        weights.append(float(q.get("weight", 1.0)))
        source_names.append(q["source"])

    fused = rrf_merge_weighted(ranked_lists, weights=weights)[:k]
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
                           "sources": [source_names[s] for s in srcs]})
    return {
        "candidates": candidates,
        "service_distribution": service_distribution,
        "query_expansion": {
            "aliases": expansion.get("aliases", []),
            "doc_hints": expansion.get("doc_hints", [])[:5],
            "queries": expansion.get("queries", []),
        },
    }

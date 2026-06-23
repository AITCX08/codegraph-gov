from .db import get_connection
from .canonical import is_canonical


def _sanitize(query: str) -> str:
    # FTS5 MATCH: quote each token to avoid syntax errors on punctuation.
    tokens = [t for t in query.replace('"', " ").split() if t]
    return " ".join(f'"{t}"' for t in tokens)


def fts_search(query: str, limit: int = 10, con=None):
    """Baseline: codegraph FTS5 keyword search over nodes_fts, canonical-filtered."""
    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        match = _sanitize(query)
        if not match:
            return []
        # over-fetch + rank: a raw LIMIT is consumed by .worktrees/ duplicates
        # (which sort no worse than canonical rows) and they then get filtered
        # out -> false-empty. ORDER BY rank gives FTS its fair best (bm25), we
        # over-fetch, drop non-canonical in Python, then trim to limit.
        sql = ("SELECT n.id, n.name, n.qualified_name, n.file_path, n.kind "
               "FROM nodes_fts f JOIN nodes n ON n.rowid = f.rowid "
               "WHERE nodes_fts MATCH ? ORDER BY rank LIMIT ?")
        # window sized for top-k display, NOT exhaustive retrieval: for a hot
        # token at a large limit it may not surface every canonical match (the
        # tail beyond the window is dropped). Fine for the gate's top-k compare.
        over = max(limit * 20, 500)
        rows = con.execute(sql, (match, over)).fetchall()
        hits = [dict(r) for r in rows if is_canonical(r["file_path"])]
        return hits[:limit]
    finally:
        if close:
            con.close()

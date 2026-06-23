from .db import get_connection
from .canonical import to_canonical_abs


def callers_counts(ids, con=None):
    """For each symbol id, count distinct callers (edges kind='calls', target=id). Batch. Read-only."""
    if not ids:
        return {}
    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        placeholders = ",".join("?" * len(ids))
        sql = (f"SELECT target, COUNT(DISTINCT source) AS n FROM edges "
               f"WHERE kind = 'calls' AND target IN ({placeholders}) GROUP BY target")
        rows = con.execute(sql, tuple(ids)).fetchall()
        counts = {r["target"]: r["n"] for r in rows}
        return {i: counts.get(i, 0) for i in ids}
    finally:
        if close:
            con.close()


def get_symbols_by_ids(ids, con=None):
    """Return {id: {id,kind,name,qualified_name,signature,abs_path,start_line}} for given ids. Read-only."""
    if not ids:
        return {}
    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        placeholders = ",".join("?" * len(ids))
        sql = (f"SELECT id, kind, name, qualified_name, signature, file_path, start_line "
               f"FROM nodes WHERE id IN ({placeholders})")
        out = {}
        for r in con.execute(sql, tuple(ids)):
            out[r["id"]] = {
                "id": r["id"], "kind": r["kind"], "name": r["name"] or "",
                "qualified_name": r["qualified_name"] or "",
                "signature": r["signature"] or "",
                "abs_path": to_canonical_abs(r["file_path"]) if r["file_path"] else "",
                "start_line": r["start_line"] or 0,
            }
        return out
    finally:
        if close:
            con.close()

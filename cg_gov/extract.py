from dataclasses import dataclass
from .db import get_connection
from .canonical import is_canonical, to_canonical_abs

REUSABLE_KINDS = ("function", "method", "class", "interface",
                  "type_alias", "struct", "enum")


@dataclass
class SymbolRecord:
    id: str
    kind: str
    name: str
    qualified_name: str
    signature: str
    docstring: str
    abs_path: str
    start_line: int


def embed_text(rec: SymbolRecord) -> str:
    parts = [rec.name or "", rec.qualified_name or "",
             rec.signature or "", (rec.docstring or "")[:300]]
    return "\n".join(p for p in parts if p)


def extract_reusable(con=None, limit: int | None = None):
    """Read reusable-kind symbols, drop non-canonical/polluted, normalize paths."""
    if limit is not None and limit <= 0:
        return []
    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        placeholders = ",".join("?" * len(REUSABLE_KINDS))
        sql = (f"SELECT id, kind, name, qualified_name, signature, docstring, "
               f"file_path, start_line FROM nodes "
               f"WHERE kind IN ({placeholders}) AND file_path IS NOT NULL")
        cur = con.execute(sql, REUSABLE_KINDS)
        out = []
        for row in cur:
            if not is_canonical(row["file_path"]):
                continue
            out.append(SymbolRecord(
                id=row["id"], kind=row["kind"], name=row["name"] or "",
                qualified_name=row["qualified_name"] or "",
                signature=row["signature"] or "",
                docstring=row["docstring"] or "",
                abs_path=to_canonical_abs(row["file_path"]),
                start_line=row["start_line"] or 0))
            if limit is not None and len(out) >= limit:
                break
        return out
    finally:
        if close:
            con.close()

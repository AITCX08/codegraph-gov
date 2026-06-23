"""Docs layer: one structured JSON source-of-truth + one rendered markdown,
both from codegraph's canonical reusable symbols (same-source dual view).

Codegraph-only auto fields. The blind-spot fields (cross-service HTTP contracts,
usage discipline, ownership) are not derivable from the index, so this generator
only points at your hand-maintained interface docs, never duplicates them.
"""
import json
from pathlib import Path
from .db import get_connection
from .extract import extract_reusable
from .config import WORKSPACE_ROOT, DOCS_MARKDOWN_OUT

WORKSPACE_PREFIX = str(WORKSPACE_ROOT).rstrip("/") + "/"
# SQLite default caps host variables in `IN (...)` at ~999; stay well under.
_BATCH = 900

# default output locations
SOURCE_OUT = (Path(__file__).resolve().parent.parent
              / "docs" / "data" / "interface_catalog.json")
MARKDOWN_OUT = DOCS_MARKDOWN_OUT


def _service_of(abs_path: str) -> str:
    if abs_path.startswith(WORKSPACE_PREFIX):
        return abs_path[len(WORKSPACE_PREFIX):].split("/", 1)[0] or "?"
    return "?"


def _rel(abs_path: str) -> str:
    """Strip the workspace prefix for compact display."""
    if abs_path.startswith(WORKSPACE_PREFIX):
        return abs_path[len(WORKSPACE_PREFIX):]
    return abs_path


# Languages whose codegraph indexer carries a real export marker (is_exported=1).
# Everywhere else (python, vue, ruby, swift, ...) is_exported is uniformly 0, so
# we derive visibility from a naming convention instead (see _is_public).
_EXPORT_AWARE_LANGS = {"go", "typescript", "tsx", "jsx"}


def _export_meta_by_ids(ids, con):
    """Batched read-only fetch of (is_exported, language) by id.

    {id: {"is_exported": bool, "language": str}}. One query carries both so we
    can derive a human-readable is_public for export-unaware languages.
    """
    out = {}
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        placeholders = ",".join("?" * len(chunk))
        sql = (f"SELECT id, is_exported, language FROM nodes "
               f"WHERE id IN ({placeholders})")
        for r in con.execute(sql, tuple(chunk)):
            out[r["id"]] = {"is_exported": bool(r["is_exported"]),
                            "language": r["language"] or ""}
    return {i: out.get(i, {"is_exported": False, "language": ""}) for i in ids}


def _is_public(name: str, is_exported: bool, language: str) -> bool:
    """Human-readable 'public interface' signal.

    For export-aware languages (go/ts/tsx/jsx) codegraph's is_exported is real,
    so trust it. For export-unaware languages (python/vue/js/...) codegraph
    gives no export marker and `visibility` is NULL, so fall back to the naming
    convention: a top-level name NOT starting with '_' is public. Keeps the raw
    is_exported untouched in the JSON/AI view.
    """
    if language in _EXPORT_AWARE_LANGS:
        return is_exported
    nm = name or ""
    # empty/anonymous name -> not a browsable public symbol
    return bool(nm) and not nm.startswith("_")


def _callers_by_ids(ids, con):
    """Batched read-only caller counts (calls-edges into id). {id: count}.

    graph.callers_counts does the right query but takes all ids in one IN clause;
    for ~28k ids that blows the ~999 host-var limit, so batch here and merge.
    """
    from .graph import callers_counts
    out = {}
    for i in range(0, len(ids), _BATCH):
        out.update(callers_counts(ids[i:i + _BATCH], con=con))
    return {i: out.get(i, 0) for i in ids}


def build_catalog(con=None) -> dict:
    """Build a service-grouped catalog of canonical reusable symbols from codegraph.

    Returns {"generated_from": "codegraph.db", "total": N,
             "services": {svc: [record, ...]}} where each record is
     {name, kind, qualified_name, signature, abs_path, start_line,
      callers, is_exported, is_public}. is_exported is codegraph's raw marker
     (kept untouched for the AI/JSON view); is_public is the human-view signal
     (raw is_exported for export-aware langs, naming convention otherwise).
     Records per service are sorted by (is_public desc, callers desc, name).
     No timestamp (determinism; caller may stamp).
    """
    recs = extract_reusable(con=con)
    ids = [r.id for r in recs]

    close = False
    if con is None:
        con = get_connection()
        close = True
    try:
        callers = _callers_by_ids(ids, con)
        meta = _export_meta_by_ids(ids, con)
    finally:
        if close:
            con.close()

    services: dict[str, list] = {}
    for r in recs:
        svc = _service_of(r.abs_path)
        m = meta[r.id]
        services.setdefault(svc, []).append({
            "name": r.name,
            "kind": r.kind,
            "qualified_name": r.qualified_name,
            "signature": r.signature,
            "abs_path": r.abs_path,
            "start_line": r.start_line,
            "callers": callers.get(r.id, 0),
            "is_exported": m["is_exported"],
            "is_public": _is_public(r.name, m["is_exported"], m["language"]),
        })

    for svc in services:
        services[svc].sort(
            key=lambda rec: (not rec["is_public"], -rec["callers"], rec["name"]))

    return {
        "generated_from": "codegraph.db",
        "total": len(recs),
        "services": services,
    }


def write_source(catalog: dict, path=SOURCE_OUT) -> Path:
    """Write the structured JSON source-of-truth (creates parent dir)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return path


# A backtick inside an inline code span cannot be backslash-escaped (CommonMark
# 6.1: backslashes are literal inside code spans), so a raw or '\\`' backtick
# would break the span. Swap it for a typographic lookalike sentinel instead.
_BACKTICK_SENTINEL = "ʼ"


def _md_escape(text: str) -> str:
    """Make a value safe for a single markdown table cell.

    - `|` (cell delimiter) -> escaped.
    - CR/CRLF normalized to LF, then newline -> '; ' so multi-field signatures
      (TS object literals) keep visual separation instead of collapsing into a
      run-on (a bare CR can also break some renderers).
    - backtick -> sentinel (see _BACKTICK_SENTINEL): can't be escaped in a code span.
    """
    return ((text or "").replace("\r\n", "\n").replace("\r", "\n")
            .replace("|", "\\|").replace("`", _BACKTICK_SENTINEL)
            .replace("\n", "; ").strip())


# Cap public rows shown per service so an export-unaware language (e.g. Python,
# where every non-underscore top-level name is public) stays browsable. Overflow
# folds into a one-line "+N more public" pointer at the JSON源. callers-desc sort
# keeps the highest-reuse symbols above the cut.
_PUBLIC_ROW_CAP = 300


def render_markdown(catalog: dict) -> str:
    """Render a browsable markdown FROM the catalog (same source, pure function).

    Human view = public interface (is_public) as tables, capped per service;
    non-public symbols collapse to a one-line count (AI view = the full JSON源).
    Deterministic: no clock, no I/O.
    """
    total = catalog.get("total", 0)
    services = catalog.get("services", {})
    # services sorted by symbol count desc, then name for stable ties
    ordered = sorted(services.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    lines = []
    lines.append("# 接口符号目录 (codegraph 自动生成)")
    lines.append("")
    lines.append("> ⚠ 自动生成, 勿手改. 真源是 codegraph.db -> "
                 "`docs/data/interface_catalog.json`.")
    lines.append("> 重新生成: `python -m cg_gov.cli gen-docs`.")
    lines.append("")
    lines.append("> 盲区字段不在这里 -- 跨服务 HTTP 契约 / 使用纪律 / 归属 "
                 "见你手维护的接口文档.")
    lines.append("")
    lines.append(f"- 来源 (generated_from): `{catalog.get('generated_from', '?')}`")
    lines.append(f"- 符号总数 (total): {total}")
    lines.append(f"- 服务数 (services): {len(services)}")
    lines.append("")
    lines.append("## 服务索引")
    lines.append("")
    lines.append("| 服务 | 符号总数 | 公开 (public) |")
    lines.append("| --- | --- | --- |")
    for svc, recs in ordered:
        public_n = sum(1 for r in recs if r["is_public"])
        lines.append(f"| {_md_escape(svc)} | {len(recs)} | {public_n} |")
    lines.append("")

    for svc, recs in ordered:
        public = [r for r in recs if r["is_public"]]
        internal_n = len(recs) - len(public)
        shown = public[:_PUBLIC_ROW_CAP]
        more_public = len(public) - len(shown)
        lines.append(f"## {_md_escape(svc)} ({len(recs)} 符号)")
        lines.append("")
        if shown:
            lines.append("| name | kind | signature | callers | file:line |")
            lines.append("| --- | --- | --- | --- | --- |")
            for r in shown:
                loc = f"{_rel(r['abs_path'])}:{r['start_line']}"
                lines.append(
                    f"| {_md_escape(r['name'])} | {_md_escape(r['kind'])} | "
                    f"`{_md_escape(r['signature'])}` | {r['callers']} | "
                    f"{_md_escape(loc)} |")
        else:
            lines.append("_(无公开符号)_")
        if more_public:
            lines.append("")
            lines.append(f"+ {more_public} more public symbols "
                         f"(query the JSON源 for full list)")
        if internal_n:
            lines.append("")
            lines.append(f"+ {internal_n} internal symbols "
                         f"(query the JSON源 for full list)")
        lines.append("")

    return "\n".join(lines)


def generate(markdown_out_path=MARKDOWN_OUT, source_out_path=SOURCE_OUT,
             con=None) -> dict:
    """build -> write JSON源 -> render -> write markdown. Returns counts."""
    catalog = build_catalog(con=con)
    src_path = write_source(catalog, source_out_path)
    md = render_markdown(catalog)
    md_path = Path(markdown_out_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    services = catalog["services"]
    per_service = {
        svc: {"total": len(recs),
              "exported": sum(1 for r in recs if r["is_exported"]),
              "public": sum(1 for r in recs if r["is_public"])}
        for svc, recs in services.items()
    }
    return {
        "total": catalog["total"],
        "services": len(services),
        "source_path": str(src_path),
        "markdown_path": str(md_path),
        "markdown_bytes": len(md.encode("utf-8")),
        "per_service": per_service,
    }

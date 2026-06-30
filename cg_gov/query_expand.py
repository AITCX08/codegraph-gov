"""Natural-language intent expansion for code reuse search."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .docs_hint import aliases_from_hints, match_doc_hints


BUILTIN_ALIASES = {
    # These defaults are intentionally small examples. Teams can add their own
    # domain vocabulary through CODEGRAPH_QUERY_ALIASES_JSON or FILE.
    "专属池": ["dedicated pool", "dedicated_user_id", "strategy group"],
    "内容池": ["content pool", "strategy_group_id"],
    "策略组": ["strategy group", "strategy_group_id"],
    "分发": ["distribution", "assign"],
    "诊断": ["diagnosis", "mainReason", "dashboard"],
    "关系": ["assignment", "mapping", "member", "resolver"],
    "绑定": ["assignment", "member", "binding"],
    "路由": ["routing", "resolver", "scope", "pool_type"],
    "重试": ["retry", "backoff", "retryWithBackoff"],
    "文件大小": ["file size", "formatFileSize", "formatBytes", "formatSize"],
    "字节": ["bytes", "formatBytes", "formatSize"],
}


def _dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _load_extra_aliases() -> dict:
    merged = {}
    raw = os.environ.get("CODEGRAPH_QUERY_ALIASES_JSON", "").strip()
    path = os.environ.get("CODEGRAPH_QUERY_ALIASES_FILE", "").strip()
    for payload in (raw, Path(path).expanduser().read_text(encoding="utf-8") if path and Path(path).expanduser().exists() else ""):
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for key, values in data.items():
                if isinstance(values, str):
                    values = [values]
                if isinstance(values, list):
                    merged[str(key)] = [str(v) for v in values]
    return merged


def _alias_map() -> dict:
    merged = {k: list(v) for k, v in BUILTIN_ALIASES.items()}
    for key, values in _load_extra_aliases().items():
        merged.setdefault(key, [])
        merged[key].extend(values)
    return {k: _dedupe(v) for k, v in merged.items()}


def _identifier_terms(aliases: list[str], max_terms: int = 12) -> list[str]:
    out = []
    for alias in aliases:
        # FTS is strict AND across tokens, so feed it compact identifiers one by one.
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", alias):
            if "_" in term or any(ch.isupper() for ch in term):
                out.append(term)
            elif term.startswith(("managed", "resolve", "assign", "retry", "format")):
                out.append(term)
        if len(out) >= max_terms:
            break
    return _dedupe(out)[:max_terms]


def expand_intent(intent: str, include_docs: bool = True) -> dict:
    """Build multiple search queries from one user intent."""
    intent = str(intent or "").strip()
    if os.environ.get("CODEGRAPH_QUERY_EXPANSION", "1").strip() == "0":
        return {
            "queries": [
                {"kind": "fts", "text": intent, "source": "fts", "weight": 1.1},
                {"kind": "semantic", "text": intent, "source": "semantic", "weight": 1.0},
            ],
            "aliases": [],
            "doc_hints": [],
        }

    aliases = []
    for term, mapped in _alias_map().items():
        if term in intent:
            aliases.extend(mapped)
    doc_hints = match_doc_hints(intent) if include_docs else []
    doc_aliases = aliases_from_hints(doc_hints)
    aliases = _dedupe(aliases)
    expanded_aliases = _dedupe(aliases + doc_aliases)

    queries = [
        {"kind": "fts", "text": intent, "source": "fts", "weight": 1.1},
        {"kind": "semantic", "text": intent, "source": "semantic", "weight": 1.0},
    ]
    if aliases:
        queries.append({
            "kind": "semantic",
            "text": " ".join([intent] + aliases),
            "source": "semantic_expanded",
            "weight": 1.0,
        })
    if doc_aliases:
        queries.append({
            "kind": "semantic",
            "text": " ".join([intent] + doc_aliases),
            "source": "semantic_docs_hint",
            "weight": 0.6,
        })
    for term in _identifier_terms(expanded_aliases):
        queries.append({
            "kind": "fts",
            "text": term,
            "source": "fts_expanded",
            "weight": 1.1 if term in aliases else 0.6,
        })

    seen = set()
    deduped = []
    for q in queries:
        key = (q["kind"], q["text"], q["source"])
        if q["text"] and key not in seen:
            seen.add(key)
            deduped.append(q)
    return {"queries": deduped, "aliases": expanded_aliases, "doc_hints": doc_hints}

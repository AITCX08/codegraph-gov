"""Low-confidence markdown hint extraction for natural-language queries.

Documentation can be stale, so hints only expand queries. Final answers must
still land on codegraph symbols / schema files.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .config import DOC_HINT_MAX_AGE_DAYS, DOC_HINT_ROOTS


_IDENT_RE = re.compile(
    r"`([A-Za-z_][A-Za-z0-9_]*(?:[./:-][A-Za-z0-9_]+)*)`"
)


def _terms(intent: str) -> list[str]:
    text = intent or ""
    terms = []
    # A compact default set; projects can still get most value by putting code
    # identifiers near business terms in their markdown docs.
    for term in (
        "专属池", "内容池", "策略组", "分发", "诊断", "关系", "绑定", "路由",
        "pool", "group", "assignment", "routing", "diagnosis",
    ):
        if term in text:
            terms.append(term)
    terms.extend(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))
    return list(dict.fromkeys(terms))


def _extract_identifiers(line: str) -> list[str]:
    out = []
    for m in _IDENT_RE.finditer(line):
        ident = m.group(1).strip()
        if len(ident) < 3:
            continue
        if "/" in ident and not ident.endswith((".js", ".ts", ".vue", ".sql", ".py", ".go")):
            continue
        out.append(ident)
    return list(dict.fromkeys(out))


def _confidence(path: Path, now: float | None = None) -> float:
    now = time.time() if now is None else now
    try:
        age_days = max(0.0, (now - path.stat().st_mtime) / 86400.0)
    except OSError:
        age_days = 9999.0
    if age_days <= DOC_HINT_MAX_AGE_DAYS:
        return 0.6
    if age_days <= DOC_HINT_MAX_AGE_DAYS * 3:
        return 0.2
    return 0.1


def match_doc_hints(intent: str, roots: list[Path] | None = None,
                    max_files: int = 2000, max_hints: int = 24) -> list[dict]:
    """Return markdown-derived aliases.

    Each hint is {term, aliases, source, confidence}. The caller should use
    aliases for query expansion only.
    """
    if os.environ.get("CODEGRAPH_DOC_HINTS", "1").strip() == "0":
        return []
    roots = DOC_HINT_ROOTS if roots is None else roots
    if not roots:
        return []
    terms = _terms(intent)
    if not terms:
        return []

    hints = []
    seen = set()
    visited = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            visited += 1
            if visited > max_files:
                break
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                matched = [t for t in terms if t and t in line]
                if not matched:
                    continue
                aliases = _extract_identifiers(line)
                if not aliases:
                    continue
                key = (str(path), lineno, tuple(aliases))
                if key in seen:
                    continue
                seen.add(key)
                hints.append({
                    "term": ",".join(matched),
                    "aliases": aliases,
                    "source": f"{path}:{lineno}",
                    "confidence": _confidence(path),
                })
                if len(hints) >= max_hints:
                    return hints
        if visited > max_files:
            break
    return hints


def aliases_from_hints(hints: list[dict], max_aliases: int = 32) -> list[str]:
    aliases = []
    for hint in sorted(hints, key=lambda h: -float(h.get("confidence", 0))):
        for alias in hint.get("aliases", []):
            if alias not in aliases:
                aliases.append(alias)
            if len(aliases) >= max_aliases:
                return aliases
    return aliases

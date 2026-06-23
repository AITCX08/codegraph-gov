"""Filter codegraph file paths down to canonical, reusable source.

A codegraph index usually also contains feature-branch worktree copies, nested
AI-tool mirror dirs, vendored third-party code, and tests. None of those are the
canonical reusable source, and left in they pollute reuse / duplicate results
(e.g. a mirror copy of a symbol outranking the real one). This module decides
which paths survive.
"""
from .config import WORKSPACE_ROOT, BLACKLIST_ROOTS  # noqa: F401 (re-exported for callers)

# Vendored/generated dir segments anywhere in the path.
#
# AI-tool mirror dirs (".claude/", ".codex/", ".cursor/" nested INSIDE a repo)
# hold byte-copies of skills / branch worktrees, not reusable source. Without
# these, mirror symbols leak in and can rank ABOVE the real source in
# semantic_search / reuse_candidates. Precise segments only -- do NOT use a bare
# "/worktrees/" which could match a legitimate path.
BLACKLIST_SEGMENTS = (
    ".data/", "node_modules/", "/vendor/", ".venv/", "/venv/",
    "/dist/", "/build/", ".git/",
    "/.claude/", "/.codex/", "/.cursor/",
)


def _first_segment(rel_path: str) -> str:
    return rel_path.split("/", 1)[0]


def is_test_path(rel_path: str) -> bool:
    p = rel_path or ""
    base = p.rsplit("/", 1)[-1]
    if "/tests/" in p or "/test/" in p or "__tests__" in p or "/__test__/" in p:
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if p.endswith(("_test.go", "_test.py", ".test.ts", ".test.tsx",
                   ".test.js", ".spec.ts", ".spec.js")):
        return True
    return False


def is_canonical(rel_path: str) -> bool:
    """True if this codegraph file_path is a canonical (deduped, non-polluted) source.

    Strategy: real checkouts live at top level (service-a/, service-b/...).
    Everything under .worktrees/ is a feature-branch duplicate copy -> drop it
    (this both dedupes to one-per-repo and removes the bulk of pollution in one cut).
    """
    if not rel_path:
        return False
    if rel_path.startswith(".worktrees/"):
        return False
    # AI-tool mirror dirs nested in a repo match via BLACKLIST_SEGMENTS (leading
    # slash). codegraph paths are repo-relative so a workspace-ROOT-level mirror
    # (e.g. ".claude/...", no leading slash) would slip past that substring check;
    # guard it explicitly, same shape as the .worktrees/ top-level case above.
    if rel_path.startswith((".claude/", ".codex/", ".cursor/")):
        return False
    if _first_segment(rel_path) in BLACKLIST_ROOTS:
        return False
    if any(seg in rel_path for seg in BLACKLIST_SEGMENTS):
        return False
    if is_test_path(rel_path):
        return False
    return True


def to_canonical_abs(rel_path: str) -> str:
    """Normalize a codegraph relative file_path to an absolute path."""
    return str(WORKSPACE_ROOT / rel_path)

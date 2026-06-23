"""Runtime configuration, resolved from environment variables.

codegraph-gov reads a codegraph index built by the upstream ``codegraph`` indexer
and answers reuse / duplicate / docs queries over it. The few deployment-specific
things -- where your code lives, where the index DB is, which top-level dirs are
vendored -- are configured here, each with a generic default so the package
imports cleanly out of the box. Point the env vars at your own layout to use it
for real.
"""
import os
from pathlib import Path

# Root of the codebase(s) the codegraph indexer scanned. codegraph stores
# repo-relative paths; this root turns them back into absolute paths for display.
WORKSPACE_ROOT = Path(
    os.environ.get("CODEGRAPH_WORKSPACE_ROOT") or str(Path.home() / "workspace")
)

# The read-only codegraph SQLite DB produced by the upstream codegraph indexer.
CODEGRAPH_DB = Path(
    os.environ.get("CODEGRAPH_DB_PATH")
    or str(WORKSPACE_ROOT / ".codegraph" / "codegraph.db")
)

# Where `cg_gov gen-docs` writes the rendered markdown catalog.
_REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_MARKDOWN_OUT = Path(
    os.environ.get("CODEGRAPH_DOCS_MARKDOWN_OUT")
    or str(_REPO_ROOT / "docs" / "interface_catalog.md")
)

# Top-level dir names to treat as vendored / third-party and drop from the
# reusable-symbol corpus (comma-separated, e.g. "vendor-lib,upstream-fork").
# Empty by default -- configure for your own layout.
BLACKLIST_ROOTS = frozenset(
    s.strip() for s in os.environ.get("CODEGRAPH_BLACKLIST_ROOTS", "").split(",")
    if s.strip()
)

"""Perception config: which repos + schema paths to watch for new DB fields.

A watched repo = {owner, repo, schema_globs}. schema_globs are fnmatch patterns
matched against a file's repo-relative path. Override the defaults via env:
  GITEA_HOST              -- Gitea host (default git.example.com)
  GITEA_OWNER             -- default repo owner / org (default your-org)
  CODEGRAPH_WATCHED_REPOS -- JSON list of {owner, repo, schema_globs}

Baseline/test files are excluded by EXCLUDE_PATTERNS at the orchestrator layer
(the parser is content-only).
"""
import json
import os

GITEA_HOST = os.environ.get("GITEA_HOST", "git.example.com")
DEFAULT_OWNER = os.environ.get("GITEA_OWNER", "your-org")

# repos + schema path globs. Override via CODEGRAPH_WATCHED_REPOS (JSON) or edit
# here. The default is an illustrative example -- replace with your own repos.
_watched_env = os.environ.get("CODEGRAPH_WATCHED_REPOS")
if _watched_env:
    WATCHED_REPOS = json.loads(_watched_env)
else:
    WATCHED_REPOS = [
        {"owner": DEFAULT_OWNER, "repo": "example-schema",
         "schema_globs": ["*.sql", "**/*.sql"]},
    ]

# orchestrator-level noise filter on FILE PATHS (not content):
#  - *baseline* / 000_baseline.sql: full snapshots, not deltas.
#  - *_test.sql: test fixtures, not real schema.
EXCLUDE_PATTERNS = ["*baseline*", "*_test.sql"]

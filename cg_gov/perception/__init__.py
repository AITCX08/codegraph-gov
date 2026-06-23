"""Perception layer: detect new DB schema fields landing on a remote Gitea.

Public API (import from cg_gov.perception):
  parse_schema_changes(old_sql, new_sql) -> [event]   # pure SQL diff core
  GiteaClient / GiteaError                              # read-only Gitea REST
  load_state / save_state                              # last_seen_sha per repo
  poll_repo / poll_all / emit_changes                  # orchestration
  WATCHED_REPOS / GITEA_HOST / DEFAULT_OWNER           # config

Live polling needs GITEA_TOKEN (read-only). Without it the CLI friendly-errors;
the network step is optional. The parser + state + orchestration are fully
unit-tested with fixtures (no network).
"""
from .parser import parse_schema_changes
from .gitea import GiteaClient, GiteaError
from .state import load_state, save_state, STATE_PATH
from .poll import poll_repo, poll_all, emit_changes, CHANGES_PATH
from .config import WATCHED_REPOS, GITEA_HOST, DEFAULT_OWNER

__all__ = [
    "parse_schema_changes",
    "GiteaClient", "GiteaError",
    "load_state", "save_state", "STATE_PATH",
    "poll_repo", "poll_all", "emit_changes", "CHANGES_PATH",
    "WATCHED_REPOS", "GITEA_HOST", "DEFAULT_OWNER",
]

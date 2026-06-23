"""Project definitions for per-project interface docs.

A "project" is not the same as a repo/service -- it's a named set of code-path
slices. One repo can contribute to several projects, and one project can span
several repos, so membership is decided by path globs (see projects.json), not
by repo names.

Path globs use ``PurePosixPath.full_match`` semantics (``**`` matches any number
of path segments), e.g. ``service-a/**/foo*`` matches foo*.py anywhere under
service-a but not bar.py.
"""
import json
from pathlib import Path, PurePosixPath
from .config import WORKSPACE_ROOT

PROJECTS_PATH = Path(__file__).resolve().parent.parent / "projects.json"


def load_projects(path: Path = PROJECTS_PATH) -> dict:
    """Read {name: {enabled, services, paths}}. Missing/corrupt -> empty."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    projects = data.get("projects", data)
    return projects if isinstance(projects, dict) else {}


def enabled_projects(path: Path = PROJECTS_PATH) -> dict:
    """Only the projects with enabled=true (the auto-refresh switch)."""
    return {k: v for k, v in load_projects(path).items() if v.get("enabled")}


def to_rel(abs_path: str) -> str:
    """Strip the workspace root prefix -> repo-relative posix path."""
    s = str(abs_path)
    root = str(WORKSPACE_ROOT).rstrip("/") + "/"
    return s[len(root):] if s.startswith(root) else s


def path_matches(abs_path: str, patterns) -> bool:
    """True if abs_path (or its repo-relative form) matches any glob in patterns.

    Uses PurePosixPath.full_match so ``**`` spans directories. Empty patterns
    never match (a project with no paths owns nothing).
    """
    if not patterns:
        return False
    pp = PurePosixPath(to_rel(abs_path))
    for pat in patterns:
        if pp.full_match(pat):
            return True
    return False

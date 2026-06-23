"""Perception: per-repo last_seen_sha state (JSON, gitignored).

Tiny persistence layer so a poll only emits events for commits newer than the
last run. Cold start (no entry for a repo) records the current head as a
baseline and emits NO events -- we never full-rescan history (the change stream
starts from "now", not from the dawn of the repo).

File: <repo>/data/perception_state.json  -> {repo: last_seen_sha}.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STATE_PATH = DATA_DIR / "perception_state.json"


def load_state(path: Path = STATE_PATH) -> dict:
    """Read {repo: last_seen_sha}. Missing/corrupt file -> empty state."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict, path: Path = STATE_PATH) -> Path:
    """Write {repo: last_seen_sha} atomically-ish (creates parent dir)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
                 encoding="utf-8")
    return p

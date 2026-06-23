"""Perception: poll orchestration (commits -> changed .sql -> events).

Ties the pieces together:
  GiteaClient (network)  +  parse_schema_changes (content)  +  state (memory)
  -> a structured change stream of added schema fields.

poll_repo walks the commits a repo gained since its last_seen_sha, and for every
changed .sql file under the repo's schema_globs (excluding baseline/test), fetches
the file content before and after, diffs it with parse_schema_changes, and tags
each event with {repo, file, commit_sha}. State advances to the new head.

Cold start: a repo with no last_seen_sha records the current head as baseline and
emits NO events (we don't rescan history).

Events are appended to data/perception_changes.jsonl (one JSON object per line).
"""
import fnmatch
import json
from pathlib import Path

from .parser import parse_schema_changes
from .config import EXCLUDE_PATTERNS
from .state import DATA_DIR
from .gitea import GiteaError

CHANGES_PATH = DATA_DIR / "perception_changes.jsonl"


def _matches_schema(path: str, schema_globs) -> bool:
    """True if `path` is a watched schema file and not excluded noise."""
    if not path.lower().endswith(".sql"):
        return False
    if not any(fnmatch.fnmatch(path, g) for g in schema_globs):
        return False
    base = path.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(path, ex) or fnmatch.fnmatch(base, ex)
           for ex in EXCLUDE_PATTERNS):
        return False
    return True


def _changed_files(commit: dict):
    """Pull the list of changed file paths from a Gitea commit object.

    Gitea's single-commit endpoint returns files as [{"filename": ...}, ...];
    some shapes use {"files": [...]} at the top or nested under "files". Be
    tolerant of both a list-of-dicts and a list-of-strings.
    """
    files = commit.get("files") or []
    out = []
    for f in files:
        if isinstance(f, str):
            out.append(f)
        elif isinstance(f, dict):
            name = f.get("filename") or f.get("path") or f.get("name")
            if name:
                out.append(name)
    return out


def _parent_shas(commit: dict):
    """Extract parent SHAs from a Gitea commit object (tolerant of shapes).

    parents[] is a list of {"sha": ...} (REST shape) or bare sha strings.
    Returns a list of sha strings (first = the diff baseline for this commit).
    """
    out = []
    for p in commit.get("parents") or []:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            sha = p.get("sha")
            if sha:
                out.append(sha)
    return out


def poll_repo(client, owner: str, repo: str, schema_globs, state: dict) -> list:
    """Poll one repo for added schema fields since state[repo]. Mutates state.

    Returns a list of events; each event is a parse_schema_changes dict tagged
    with {repo, file, commit_sha}. Cold start (repo not in state) -> records
    head as baseline, returns []. State[repo] advances to the newest head.
    """
    commits = client.list_commits(owner, repo)
    if not commits:
        return []
    head_sha = commits[0].get("sha")

    last_seen = state.get(repo)
    if last_seen is None:
        # cold start: baseline only, no events (don't rescan history)
        state[repo] = head_sha
        return []
    if last_seen == head_sha:
        return []  # nothing new

    # commits are newest-first; take the ones strictly after last_seen.
    # KNOWN LIMITATION (deferred live phase): if last_seen scrolled out of the
    # newest list_commits() window the loop never finds it and replays the whole
    # window. Bounded + self-healing (per-commit parent diffs, state still
    # advances to head), but can duplicate events into the append-only stream.
    # For a low-frequency schema poller the window is ample; wire compare() here
    # if backfill depth ever matters.
    new_commits = []
    for c in commits:
        if c.get("sha") == last_seen:
            break
        new_commits.append(c)
    # process oldest-first so per-file old->new diffs chain naturally
    new_commits.reverse()

    events: list = []
    # baseline for the oldest new commit; advances along the chain so a commit
    # missing parents[] diffs against the true previous commit, not last_seen.
    prev_sha = last_seen
    for commit in new_commits:
        sha = commit.get("sha")
        # the single-commit endpoint carries changed files AND a full parents[];
        # if the list-commits payload is missing EITHER, fetch the richer commit
        # so the parent_sha is the commit's true parent -- never blindly fall
        # back to last_seen (that would diff commits 2..N against the wrong base).
        files = _changed_files(commit)
        parents = _parent_shas(commit)
        if not files or not parents:
            try:
                full = client.get_commit(owner, repo, sha)
                files = files or _changed_files(full)
                parents = parents or _parent_shas(full)
            except AttributeError:
                pass            # client has no get_commit (e.g. a slim mock)
            except GiteaError:
                pass            # transient API error on ONE commit: degrade to
                                # prev_sha baseline, don't sink the whole poll
                                # (state won't advance past head -> retried next run)
        # first parent = this commit's diff baseline; if still unknown, the
        # chained previous new_commit's sha is correct (oldest-first), falling
        # back to last_seen only for the very first commit in the batch.
        parent_sha = parents[0] if parents else prev_sha
        for path in files:
            if not _matches_schema(path, schema_globs):
                continue
            old_sql = client.get_file(owner, repo, path, parent_sha)
            new_sql = client.get_file(owner, repo, path, sha)
            for ev in parse_schema_changes(old_sql, new_sql):
                events.append({**ev, "repo": repo, "file": path, "commit_sha": sha})
        prev_sha = sha

    state[repo] = head_sha
    return events


def poll_all(config_repos, client, state: dict) -> list:
    """Poll every watched repo; concatenate events. Mutates state in place."""
    all_events: list = []
    for rc in config_repos:
        all_events.extend(
            poll_repo(client, rc["owner"], rc["repo"], rc["schema_globs"], state))
    return all_events


def _event_key(ev: dict):
    """Stable identity of a change event for dedup against the existing stream.

    Same (repo, file, commit_sha, change_type, object, table, field) = the same
    schema change. Used so a re-poll that replays a commit (e.g. last_seen
    scrolled out of the commit window) does NOT append duplicate JSONL lines.
    """
    return (ev.get("repo"), ev.get("file"), ev.get("commit_sha"),
            ev.get("change_type"), ev.get("object"),
            (ev.get("table") or "").lower(), (ev.get("field") or "").lower())


def emit_changes(events, path: Path = CHANGES_PATH):
    """Append NEW events to the JSONL change stream, idempotently.

    Existing keys are read from the file first; events whose _event_key already
    appears are skipped, so replays don't double-write. Also de-dups within the
    same batch. Returns the path.
    """
    if not events:
        return path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    seen = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(_event_key(json.loads(line)))
            except json.JSONDecodeError:
                continue  # tolerate a partial/corrupt trailing line

    with p.open("a", encoding="utf-8") as fh:
        for ev in events:
            key = _event_key(ev)
            if key in seen:
                continue
            seen.add(key)
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return p

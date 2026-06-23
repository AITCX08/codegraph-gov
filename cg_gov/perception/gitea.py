"""Perception: read-only Gitea REST client (stdlib only, mockable).

No new dependency -- HTTP is stdlib `urllib.request`. The transport is
INJECTABLE: pass `opener=callable(url, headers) -> (status, body_bytes)` and the
client never touches the network. Tests inject a fake opener returning fixture
bytes; production leaves opener=None and gets a real urllib GET. All methods are
read-only GETs.

Endpoints (Gitea REST v1, host like https://git.example.com):
  - list_commits -> GET /api/v1/repos/{owner}/{repo}/commits?sha=&limit=
  - compare      -> GET /api/v1/repos/{owner}/{repo}/compare/{base}...{head}
  - get_file     -> GET /api/v1/repos/{owner}/{repo}/raw/{path}?ref={sha}

Token: passed in via constructor (the CLI reads it from env GITEA_TOKEN). Never
hardcoded, never logged.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

API_PREFIX = "/api/v1"


def _real_opener(url: str, headers: dict, *, timeout: int = 15):
    """Default transport: a plain stdlib GET. Returns (status, body_bytes).

    timeout is mandatory: never make an unbounded HTTP call.

    urllib RAISES HTTPError on non-2xx instead of returning it; we normalize
    that back to (status, body) so the GiteaError / 404-tolerance layer in
    _get_raw / get_file works against the real transport exactly like the fake
    test opener (which already returns, not raises). Without this, a 404 -- the
    expected shape when a file did not yet exist at the baseline ref -- escapes
    as a raw HTTPError and crashes the poll.
    """
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https host, read-only)
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class GiteaClient:
    """Thin read-only Gitea API client. HTTP transport is injectable for tests."""

    def __init__(self, host: str, token: str, *, opener=None, timeout: int = 15):
        # normalize host -> scheme + authority, no trailing slash
        self.host = host.rstrip("/")
        if not self.host.startswith(("http://", "https://")):
            self.host = "https://" + self.host
        self._token = token
        self._timeout = timeout
        # opener(url, headers) -> (status, body_bytes). Default = real urllib GET.
        self._opener = opener or (lambda url, headers: _real_opener(
            url, headers, timeout=self._timeout))

    # --- low-level ---------------------------------------------------------
    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"token {self._token}"
        return h

    def _url(self, path: str, query: dict | None = None) -> str:
        url = self.host + path
        if query:
            # drop None values so optional params stay out of the URL
            q = {k: v for k, v in query.items() if v is not None}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        return url

    def _get_raw(self, path: str, query: dict | None = None) -> bytes:
        status, body = self._opener(self._url(path, query), self._headers())
        if status >= 400:
            raise GiteaError(status, path, body)
        return body

    def _get_json(self, path: str, query: dict | None = None):
        return json.loads(self._get_raw(path, query).decode("utf-8"))

    # --- read-only API ------------------------------------------------------
    def list_commits(self, owner: str, repo: str, since_sha: str | None = None,
                     limit: int = 50) -> list:
        """GET recent commits on the default branch (newest first).

        since_sha is the starting ref (Gitea `sha=`); pass None for HEAD. The
        orchestrator handles "since last seen" semantics by trimming the
        returned list (Gitea has no native exclusive-since on this endpoint).
        """
        return self._get_json(
            f"{API_PREFIX}/repos/{owner}/{repo}/commits",
            {"sha": since_sha, "limit": limit})

    def get_commit(self, owner: str, repo: str, sha: str) -> dict:
        """GET a single commit incl. its changed files[] (newest Gitea shape)."""
        return self._get_json(
            f"{API_PREFIX}/repos/{owner}/{repo}/git/commits/"
            + urllib.parse.quote(sha, safe="."))

    def compare(self, owner: str, repo: str, base_sha: str, head_sha: str) -> dict:
        """GET the diff between two refs: {commits, total_commits, files, ...}."""
        spec = f"{base_sha}...{head_sha}"
        # the {base}...{head} segment goes in the PATH; encode the slashes-safe ref
        return self._get_json(
            f"{API_PREFIX}/repos/{owner}/{repo}/compare/"
            + urllib.parse.quote(spec, safe="."))

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> str:
        """GET raw file content at a ref. Returns decoded text ("" on 404)."""
        try:
            body = self._get_raw(
                f"{API_PREFIX}/repos/{owner}/{repo}/raw/"
                + urllib.parse.quote(path),
                {"ref": ref})
        except GiteaError as e:
            if e.status == 404:
                return ""  # file did not exist at this ref (e.g. newly added)
            raise
        return body.decode("utf-8", errors="replace")


class GiteaError(RuntimeError):
    """Non-2xx response from Gitea (carries status + path for diagnosis)."""

    def __init__(self, status: int, path: str, body: bytes = b""):
        self.status = status
        self.path = path
        snippet = body[:200].decode("utf-8", errors="replace") if body else ""
        super().__init__(f"Gitea {status} on {path}: {snippet}")

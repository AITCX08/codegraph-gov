import json
from cg_gov.perception import GiteaClient, GiteaError


def _fake_opener(responses):
    """Build an injectable opener: dict {url-substring: (status, body_bytes)}."""
    calls = []

    def opener(url, headers):
        calls.append((url, headers))
        for key, resp in responses.items():
            if key in url:
                return resp
        return 404, b"not found"

    opener.calls = calls
    return opener


def test_list_commits_builds_url_and_auth_header():
    body = json.dumps([{"sha": "abc"}]).encode()
    opener = _fake_opener({"/commits": (200, body)})
    c = GiteaClient("git.example.com", "FAKE_TOKEN", opener=opener)
    assert c.list_commits("acme", "repo-x") == [{"sha": "abc"}]
    url, headers = opener.calls[0]
    assert url.startswith(
        "https://git.example.com/api/v1/repos/acme/repo-x/commits")
    assert headers["Authorization"] == "token FAKE_TOKEN"


def test_host_normalized_to_https():
    opener = _fake_opener({"/commits": (200, b"[]")})
    c = GiteaClient("git.example.com", "t", opener=opener)
    c.list_commits("acme", "repo-x")
    assert opener.calls[0][0].startswith("https://")


def test_get_file_returns_empty_on_404():
    opener = _fake_opener({})  # everything 404s
    c = GiteaClient("git.example.com", "t", opener=opener)
    assert c.get_file("acme", "repo-x", "schema.sql", "sha0") == ""


def test_non_404_error_raises():
    opener = _fake_opener({"/commits": (500, b"boom")})
    c = GiteaClient("git.example.com", "t", opener=opener)
    try:
        c.list_commits("acme", "repo-x")
        assert False, "expected GiteaError"
    except GiteaError as e:
        assert e.status == 500

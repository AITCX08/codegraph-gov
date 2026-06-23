from cg_gov.fts import _sanitize


def test_sanitize_quotes_each_token():
    assert _sanitize("format byte size") == '"format" "byte" "size"'


def test_sanitize_strips_embedded_quotes():
    assert _sanitize('a "b" c') == '"a" "b" "c"'


def test_sanitize_empty():
    assert _sanitize("") == ""
    assert _sanitize("   ") == ""

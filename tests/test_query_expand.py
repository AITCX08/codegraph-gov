from cg_gov.docs_hint import match_doc_hints
from cg_gov.query_expand import expand_intent


def test_chinese_business_terms_expand_to_code_terms(monkeypatch):
    monkeypatch.setattr("cg_gov.query_expand.match_doc_hints", lambda _intent: [])
    res = expand_intent("查一下达人专属池和内容池路由")
    aliases = set(res["aliases"])
    assert "dedicated_user_id" in aliases
    assert "strategy_group_id" in aliases
    assert any(q["source"] == "semantic_expanded" for q in res["queries"])
    assert any(q["kind"] == "fts" and q["text"] == "dedicated_user_id" for q in res["queries"])


def test_extra_aliases_json(monkeypatch):
    monkeypatch.setenv(
        "CODEGRAPH_QUERY_ALIASES_JSON",
        '{"达人专属池": ["managed_strategy_group", "managed_dedicated_assignment"]}',
    )
    monkeypatch.setattr("cg_gov.query_expand.match_doc_hints", lambda _intent: [])
    res = expand_intent("查一下达人专属池关系")
    assert "managed_strategy_group" in res["aliases"]
    assert "managed_dedicated_assignment" in res["aliases"]


def test_docs_hint_extracts_backtick_identifiers(tmp_path):
    doc = tmp_path / "p14.md"
    doc.write_text(
        "达人专属池 关系落在 `managed_strategy_group.dedicated_user_id` "
        "和 `managed_dedicated_assignment`。\n",
        encoding="utf-8",
    )
    hints = match_doc_hints("查一下达人专属池关系", roots=[tmp_path])
    aliases = {a for h in hints for a in h["aliases"]}
    assert "managed_strategy_group.dedicated_user_id" in aliases
    assert "managed_dedicated_assignment" in aliases
    assert hints[0]["confidence"] == 0.6


def test_expand_uses_docs_hints(monkeypatch):
    monkeypatch.setattr(
        "cg_gov.query_expand.match_doc_hints",
        lambda _intent: [{
            "term": "专属池",
            "aliases": ["resolveDistributorScope"],
            "source": "/tmp/x.md:1",
            "confidence": 0.6,
        }],
    )
    res = expand_intent("查一下专属池关系")
    assert "resolveDistributorScope" in res["aliases"]
    assert any(q["source"] == "semantic_docs_hint" for q in res["queries"])

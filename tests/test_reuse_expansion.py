from cg_gov import reuse


class _FakeEmbedder:
    def embed(self, texts):
        raise AssertionError("semantic_search is monkeypatched")


def test_reuse_uses_expanded_queries_and_sources(monkeypatch):
    seen_semantic = []
    seen_fts = []

    def fake_expand(_intent):
        return {
            "aliases": ["managed_dedicated_assignment"],
            "doc_hints": [],
            "queries": [
                {"kind": "semantic", "text": "中文", "source": "semantic", "weight": 1.0},
                {"kind": "semantic", "text": "managed_dedicated_assignment", "source": "semantic_expanded", "weight": 1.0},
                {"kind": "fts", "text": "managed_dedicated_assignment", "source": "fts_expanded", "weight": 1.1},
            ],
        }

    def fake_semantic(text, _embedder, k=10):
        seen_semantic.append(text)
        if text == "managed_dedicated_assignment":
            return [{"id": "target", "name": "replaceAssignmentsForDistributor"}]
        return []

    def fake_fts(text, limit=10):
        seen_fts.append(text)
        if text == "managed_dedicated_assignment":
            return [{"id": "target", "name": "replaceAssignmentsForDistributor"}]
        return []

    class FakeCon:
        def close(self):
            pass

    monkeypatch.setattr(reuse, "expand_intent", fake_expand)
    monkeypatch.setattr(reuse, "semantic_search", fake_semantic)
    monkeypatch.setattr(reuse, "fts_search", fake_fts)
    monkeypatch.setattr(reuse, "get_connection", lambda: FakeCon())
    monkeypatch.setattr(reuse, "get_symbols_by_ids", lambda ids, con=None: {
        "target": {
            "id": "target",
            "kind": "function",
            "name": "replaceAssignmentsForDistributor",
            "qualified_name": "",
            "signature": "",
            "abs_path": "/workspace/service/src/models/managedDedicatedAssignment.js",
            "start_line": 33,
        }
    })
    monkeypatch.setattr(reuse, "callers_counts", lambda ids, con=None: {"target": 0})

    res = reuse.reuse_candidates("查一下专属池关系", k=5, embedder=_FakeEmbedder())
    assert seen_semantic == ["中文", "managed_dedicated_assignment"]
    assert seen_fts == ["managed_dedicated_assignment"]
    assert res["candidates"][0]["name"] == "replaceAssignmentsForDistributor"
    assert set(res["candidates"][0]["sources"]) == {"semantic_expanded", "fts_expanded"}
    assert res["query_expansion"]["aliases"] == ["managed_dedicated_assignment"]

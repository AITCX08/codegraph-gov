from cg_gov.fuse import rrf_merge, rrf_merge_weighted


def test_rrf_merges_and_ranks():
    # "a" is ranked high in both lists -> it should win the fused order
    fused = rrf_merge([["a", "b", "c"], ["a", "c", "d"]])
    ids = [i for i, _score, _src in fused]
    assert ids[0] == "a"
    assert set(ids) == {"a", "b", "c", "d"}


def test_rrf_score_and_sources():
    fused = rrf_merge([["x", "y"], ["y"]])
    by_id = {i: (score, src) for i, score, src in fused}
    # y appears in both lists -> both source indices recorded
    assert by_id["y"][1] == [0, 1]
    # x only in list 0
    assert by_id["x"][1] == [0]
    # presence in both lists makes y outscore x
    assert by_id["y"][0] > by_id["x"][0]


def test_rrf_dedupes_within_a_list():
    # a repeated id in one list counts only its best (first) rank
    fused = rrf_merge([["a", "a", "b"]])
    by_id = {i: score for i, score, _src in fused}
    assert by_id["a"] == 1.0 / (60 + 1)


def test_rrf_empty():
    assert rrf_merge([]) == []
    assert rrf_merge([[], []]) == []


def test_weighted_rrf_downweights_hint_lists():
    fused = rrf_merge_weighted([["a"], ["b"]], weights=[1.0, 0.1])
    assert [i for i, _score, _src in fused] == ["a", "b"]

def rrf_merge(ranked_lists, c: int = 60):
    """Reciprocal Rank Fusion of multiple ranked id lists.

    ranked_lists: list of lists of ids, each ordered best-first.
    Returns [(id, score, source_list_indices)] sorted by descending fused score.
    score(id) = sum over lists containing id of 1 / (c + rank), rank is 1-based.
    """
    scores = {}
    sources = {}
    for li, ids in enumerate(ranked_lists):
        seen = set()
        for rank, _id in enumerate(ids, start=1):
            if _id in seen:          # keep only the best (first) rank per id per list
                continue
            seen.add(_id)
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (c + rank)
            sources.setdefault(_id, set()).add(li)
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    return [(_id, score, sorted(sources[_id])) for _id, score in ordered]

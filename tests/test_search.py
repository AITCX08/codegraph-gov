import numpy as np
from cg_gov.search import cosine_topk


def test_cosine_topk_orders_by_similarity():
    q = np.array([1.0, 0.0], dtype=np.float32)
    m = np.array([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7]], dtype=np.float32)
    top = cosine_topk(q, m, k=3)
    idx = [i for i, _s in top]
    assert idx[0] == 0   # identical direction ranks first
    assert idx[-1] == 1  # orthogonal vector ranks last


def test_cosine_topk_k_limit():
    q = np.array([1.0, 0.0], dtype=np.float32)
    m = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    assert len(cosine_topk(q, m, k=2)) == 2

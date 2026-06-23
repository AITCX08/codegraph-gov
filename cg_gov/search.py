import json
from functools import lru_cache
from pathlib import Path
import numpy as np

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def cosine_topk(query_vec: np.ndarray, matrix: np.ndarray, k: int = 10):
    """Return [(row_index, score), ...] top-k by cosine similarity."""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
    scores = m @ q
    idx = np.argsort(-scores)[:k]
    return [(int(i), float(scores[i])) for i in idx]


@lru_cache(maxsize=1)
def load_index(data_dir: Path = DATA_DIR):
    """Load (vecs, meta) from disk, cached for the process lifetime.

    NOTE: @lru_cache means a long-lived process (e.g. the MCP server) keeps the
    index in memory; rebuilding emb.npy via `cli index` needs a process restart
    to take effect.
    """
    vecs = np.load(data_dir / "emb.npy")
    meta = json.loads((data_dir / "meta.json").read_text())
    return vecs, meta


def semantic_search(intent: str, embedder, k: int = 10, data_dir: Path = DATA_DIR):
    vecs, meta = load_index(data_dir)
    qvec = embedder.embed([intent])[0]
    hits = cosine_topk(qvec, vecs, k=k)
    return [{**meta[i], "score": s} for i, s in hits]

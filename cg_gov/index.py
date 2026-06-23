import json
import time
from pathlib import Path
import numpy as np
from .extract import extract_reusable, embed_text
from .embed import LocalFastembed

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def build_index(embedder=None, limit: int | None = None, batch: int = 256,
                data_dir: Path = DATA_DIR):
    """Embed canonical reusable symbols, save emb.npy + meta.json. Never writes codegraph.db."""
    embedder = embedder or LocalFastembed()
    records = extract_reusable(limit=limit)
    texts = [embed_text(r) for r in records]
    t0 = time.time()
    vecs_parts = []
    for i in range(0, len(texts), batch):
        vecs_parts.append(embedder.embed(texts[i:i + batch]))
        print(f"  embedded {min(i + batch, len(texts))}/{len(texts)}", flush=True)
    vecs = np.vstack(vecs_parts) if vecs_parts else np.zeros((0, 384), dtype=np.float32)
    data_dir.mkdir(parents=True, exist_ok=True)
    np.save(data_dir / "emb.npy", vecs)
    meta = [{"id": r.id, "kind": r.kind, "name": r.name,
             "qualified_name": r.qualified_name, "signature": r.signature,
             "abs_path": r.abs_path, "start_line": r.start_line} for r in records]
    (data_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    # index_info.json: lets search/gate warn when reasoning over a partial index
    # (a --limit build covers only part of the corpus; FTS queries the full db,
    # so gate conclusions drawn on a partial index are misleading).
    info = {"count": len(records), "limit": limit, "embedder": embedder.name}
    (data_dir / "index_info.json").write_text(json.dumps(info, ensure_ascii=False))
    dt = time.time() - t0
    print(f"indexed {len(records)} symbols with {embedder.name} in {dt:.1f}s")
    return len(records), dt

import os
import numpy as np
from .config import EMBED_MODEL


class LocalFastembed:
    """Local ONNX embedding (no network). The default embedder."""

    def __init__(self, model: str | None = None):
        from fastembed import TextEmbedding
        model = model or EMBED_MODEL
        self._model = TextEmbedding(model_name=model)
        self._model_name = model

    @property
    def name(self) -> str:
        return f"local:{self._model_name}"

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self._model.embed(texts)), dtype=np.float32)


class ApiEmbed:
    """API embedding (OpenAI-compatible). Needs OPENAI_API_KEY."""

    def __init__(self, model: str = "text-embedding-3-small",
                 api_key: str | None = None, base_url: str | None = None):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"))
        self._model = model

    @property
    def name(self) -> str:
        return f"api:{self._model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return np.array([d.embedding for d in resp.data], dtype=np.float32)

"""Text embeddings for RAG: turns a passage (or a question) into a vector, so passages with the same
MEANING are found even when they share no words with the question.

Uses any OpenAI-compatible /embeddings endpoint (OpenAI, or OpenRouter). Vectors are unit length, so
a dot product is the cosine similarity. 512 dimensions keep storage small (about 2 KB per passage as float32).
"""
import logging

import httpx
import numpy as np

log = logging.getLogger("tc.embeddings")
DIMS = 512
BATCH = 64


class EmbeddingError(Exception):
    pass


class Embedder:
    def __init__(self, base_url: str, api_key: str, model: str, *, dims: int = DIMS, timeout_s: float = 30.0):
        self.base_url, self.api_key, self.model, self.dims, self.timeout_s = base_url.rstrip("/"), api_key, model, dims, timeout_s

    def embed(self, texts: list[str]) -> np.ndarray:
        """Returns an (n, dims) float32 array of unit vectors. Blocking: call it from a worker thread."""
        if not texts:
            return np.zeros((0, self.dims), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            batch = [t[:6000] or " " for t in texts[i:i + BATCH]]
            body: dict = {"model": self.model, "input": batch}
            if "text-embedding-3" in self.model:                      # these models can return shorter vectors
                body["dimensions"] = self.dims
            try:
                res = httpx.post(f"{self.base_url}/embeddings", headers={"authorization": f"Bearer {self.api_key}"}, json=body, timeout=self.timeout_s)
            except httpx.HTTPError as e:
                raise EmbeddingError(f"could not reach the embedding service ({e.__class__.__name__})")
            if res.status_code >= 400:
                log.warning("embeddings.vendor_error status=%s", res.status_code)
                raise EmbeddingError(f"the embedding service returned {res.status_code}")
            try:
                data = sorted(res.json()["data"], key=lambda d: d["index"])
                out.extend(d["embedding"] for d in data)
            except (KeyError, TypeError, ValueError):
                raise EmbeddingError("unexpected reply from the embedding service")
        m = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(raw: bytes) -> np.ndarray:
    return np.frombuffer(bytes(raw), dtype=np.float32)


def get_embedder(settings) -> Embedder | None:
    """An embedder if some configured key can create embeddings, else None (RAG then uses keyword search only)."""
    if settings.openai_api_key:
        return Embedder(settings.openai_base_url, settings.openai_api_key, settings.embedding_model)
    if settings.openrouter_api_key:
        model = settings.embedding_model if "/" in settings.embedding_model else f"openai/{settings.embedding_model}"
        return Embedder("https://openrouter.ai/api/v1", settings.openrouter_api_key, model)
    return None

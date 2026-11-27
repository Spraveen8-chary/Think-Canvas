"""The textbook library: add a book, search it. Uses rag.py for parsing/ranking, the repository for storage
and (optionally) an embedder for meaning-based search."""
import logging
import time

import numpy as np
from bson import ObjectId

from ..core.errors import BadRequest, NotFound
from ..core.logging import kv
from ..repositories.library import LibraryRepository
from . import rag
from .embeddings import Embedder, EmbeddingError, from_bytes, to_bytes

log = logging.getLogger("tc.library")


class LibraryService:
    def __init__(self, repo: LibraryRepository, embedder: Embedder | None = None):
        self.repo, self.embedder = repo, embedder

    def ingest(self, user_id: ObjectId, filename: str, data: bytes) -> dict:
        started = time.perf_counter()
        pages = rag.extract_pages(filename, data)
        chunks = rag.chunk_pages(pages)
        if not chunks:
            raise BadRequest("No readable text found. Scanned PDFs (pictures of pages) are not supported.")
        embedded = False
        if self.embedder:                                   # meaning-based search; if this fails the book still works with keywords
            try:
                vectors = self.embedder.embed([c["text"] for c in chunks])
                for c, v in zip(chunks, vectors):
                    c["emb"] = to_bytes(v)
                embedded = True
            except EmbeddingError as e:
                for c in chunks:
                    c.pop("emb", None)
                log.warning("library.embed_failed %s", kv(name=filename[:60], error=e))
        doc = self.repo.add(user_id, filename[:120], len(pages), chunks)
        log.info("library.ingest %s", kv(user=user_id, name=filename[:60], pages=len(pages), chunks=len(chunks), embedded=embedded, ms=round((time.perf_counter() - started) * 1000)))
        return doc

    def reindex(self, user_id: ObjectId, doc_id: ObjectId) -> dict:
        """Adds vectors to a book that was uploaded before embeddings existed (or while the service was down)."""
        doc = self.repo.get(user_id, doc_id)
        if not doc:
            raise NotFound("Not found")
        if not self.embedder:
            raise BadRequest("No embedding service is configured (set OPENAI_API_KEY).")
        todo = self.repo.chunks_without_embedding(doc_id)
        try:
            vectors = self.embedder.embed([c["text"] for c in todo])
        except EmbeddingError as e:
            raise BadRequest(f"Could not create embeddings: {e}")
        self.repo.set_embeddings(doc_id, [(c["_id"], to_bytes(v)) for c, v in zip(todo, vectors)])
        log.info("library.reindex %s", kv(user=user_id, doc=doc_id, chunks=len(todo)))
        return self.repo.get(user_id, doc_id)

    def set_active(self, user_id: ObjectId, doc_id: ObjectId, active: bool) -> None:
        if not self.repo.set_active(user_id, doc_id, active):
            raise NotFound("Not found")

    def delete(self, user_id: ObjectId, doc_id: ObjectId) -> None:
        if not self.repo.delete(user_id, doc_id):
            raise NotFound("Not found")
        log.info("library.delete %s", kv(user=user_id, doc=doc_id))

    def has_active(self, user_id: ObjectId) -> bool:
        return bool(self.repo.active_names(user_id))

    # ---- search ------------------------------------------------------------------------------------------------
    def _by_meaning(self, doc_ids: list[ObjectId], query: str, n: int) -> list[dict]:
        """Passages closest in meaning to the query (cosine similarity of embeddings), best first."""
        if not self.embedder:
            return []
        rows = self.repo.embedded_chunks(doc_ids)
        if not rows:
            return []
        try:
            q = self.embedder.embed([query])[0]
        except EmbeddingError as e:
            log.warning("library.query_embed_failed %s", kv(error=e))
            return []
        matrix = np.stack([from_bytes(r["emb"]) for r in rows])
        if matrix.shape[1] != q.shape[0]:                    # vectors from a different embedding setup
            return []
        sims = matrix @ q
        order = np.argsort(-sims)[:n]
        return [{**rows[i], "sim": float(sims[i])} for i in order if sims[i] >= rag.MIN_SIMILARITY]

    def search(self, user_id: ObjectId, query: str, k: int = rag.TOP_K, context: str = "") -> list[dict]:
        """Best passages from the user's switched-on books: [{"source", "page", "text"}].

        `context` is the previous question of the conversation: it is added to the meaning search so a
        follow-up like "and what about its units?" still finds the right passage."""
        query = query.strip()
        names = self.repo.active_names(user_id)
        if not query or not names:
            return []
        ids = list(names)
        by_meaning = self._by_meaning(ids, f"{context.strip()} {query}".strip() if context else query, 12)
        by_keyword = self.repo.search(ids, query, 12)
        rows = {r["_id"]: r for r in by_keyword}
        rows.update({r["_id"]: r for r in by_meaning})
        best = rag.rrf([r["_id"] for r in by_meaning], [r["_id"] for r in by_keyword])[:k]
        return [{"source": names[rows[i]["doc_id"]], "page": rows[i]["page"], "text": rows[i]["text"][:rag.EXCERPT_CHARS]} for i in best]

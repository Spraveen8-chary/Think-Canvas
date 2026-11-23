"""The textbook library: add a book, search it. Uses rag.py for parsing and the repository for storage."""
import logging
import time

from bson import ObjectId

from ..core.errors import BadRequest, NotFound
from ..core.logging import kv
from ..repositories.library import LibraryRepository
from . import rag

log = logging.getLogger("tc.library")


class LibraryService:
    def __init__(self, repo: LibraryRepository):
        self.repo = repo

    def ingest(self, user_id: ObjectId, filename: str, data: bytes) -> dict:
        started = time.perf_counter()
        pages = rag.extract_pages(filename, data)
        chunks = rag.chunk_pages(pages)
        if not chunks:
            raise BadRequest("No readable text found. Scanned PDFs (pictures of pages) are not supported.")
        doc = self.repo.add(user_id, filename[:120], len(pages), chunks)
        log.info("library.ingest %s", kv(user=user_id, name=filename[:60], pages=len(pages), chunks=len(chunks), ms=round((time.perf_counter() - started) * 1000)))
        return doc

    def set_active(self, user_id: ObjectId, doc_id: ObjectId, active: bool) -> None:
        if not self.repo.set_active(user_id, doc_id, active):
            raise NotFound("Not found")

    def delete(self, user_id: ObjectId, doc_id: ObjectId) -> None:
        if not self.repo.delete(user_id, doc_id):
            raise NotFound("Not found")
        log.info("library.delete %s", kv(user=user_id, doc=doc_id))

    def has_active(self, user_id: ObjectId) -> bool:
        return bool(self.repo.active_names(user_id))

    def search(self, user_id: ObjectId, query: str, k: int = rag.TOP_K) -> list[dict]:
        """Best passages from the user's switched-on books: [{"source", "page", "text"}]."""
        query = query.strip()
        names = self.repo.active_names(user_id)
        if not query or not names:
            return []
        rows = self.repo.search(list(names), query, k)
        return [{"source": names[r["doc_id"]], "page": r["page"], "text": r["text"][:rag.EXCERPT_CHARS]} for r in rows]

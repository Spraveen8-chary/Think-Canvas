"""Data access for the textbook library: `documents` (one per file) and `chunks` (passages for search)."""
from datetime import datetime, timezone

import logging

from bson import Binary, ObjectId


log = logging.getLogger("tc.library")


class LibraryRepository:
    def __init__(self, db):
        self.documents, self.chunks = db.documents, db.chunks

    def for_user(self, user_id: ObjectId) -> list[dict]:
        return list(self.documents.find({"user_id": user_id}).sort("created_at", -1))

    def add(self, user_id: ObjectId, name: str, pages: int, chunks: list[dict]) -> dict:
        """Each chunk is {"page", "text"} and optionally "emb" (float32 bytes) for meaning-based search."""
        embedded = bool(chunks) and all("emb" in c for c in chunks)
        doc = {"user_id": user_id, "name": name, "pages": pages, "chunks": len(chunks), "active": True, "embedded": embedded, "created_at": datetime.now(timezone.utc)}
        doc["_id"] = self.documents.insert_one(doc).inserted_id
        self.chunks.insert_many([{"doc_id": doc["_id"], "user_id": user_id, **{k: (Binary(v) if k == "emb" else v) for k, v in c.items()}} for c in chunks])
        return doc

    def get(self, user_id: ObjectId, doc_id: ObjectId) -> dict | None:
        return self.documents.find_one({"_id": doc_id, "user_id": user_id})

    def chunks_without_embedding(self, doc_id: ObjectId) -> list[dict]:
        return list(self.chunks.find({"doc_id": doc_id, "emb": {"$exists": False}}, {"text": 1}))

    def set_embeddings(self, doc_id: ObjectId, pairs: list[tuple[ObjectId, bytes]]) -> None:
        for chunk_id, raw in pairs:
            self.chunks.update_one({"_id": chunk_id}, {"$set": {"emb": Binary(raw)}})
        self.documents.update_one({"_id": doc_id}, {"$set": {"embedded": not self.chunks_without_embedding(doc_id)}})

    def embedded_chunks(self, doc_ids: list[ObjectId]) -> list[dict]:
        """Passages of these documents that have a vector: used for meaning-based search."""
        return list(self.chunks.find({"doc_id": {"$in": doc_ids}, "emb": {"$exists": True}}, {"emb": 1, "page": 1, "text": 1, "doc_id": 1}))

    def set_active(self, user_id: ObjectId, doc_id: ObjectId, active: bool) -> bool:
        return self.documents.update_one({"_id": doc_id, "user_id": user_id}, {"$set": {"active": active}}).matched_count > 0

    def delete(self, user_id: ObjectId, doc_id: ObjectId) -> bool:
        if not self.documents.delete_one({"_id": doc_id, "user_id": user_id}).deleted_count:
            return False
        self.chunks.delete_many({"doc_id": doc_id})
        return True

    def active_names(self, user_id: ObjectId) -> dict[ObjectId, str]:
        return {d["_id"]: d["name"] for d in self.documents.find({"user_id": user_id, "active": True}, {"name": 1})}

    def search(self, doc_ids: list[ObjectId], query: str, k: int) -> list[dict]:
        """MongoDB $text (keyword) search over the given documents, best match first."""
        try:
            return list(
                self.chunks.find(
                    {"$text": {"$search": query}, "doc_id": {"$in": doc_ids}},
                    {"score": {"$meta": "textScore"}, "page": 1, "text": 1, "doc_id": 1},
                ).sort([("score", {"$meta": "textScore"})]).limit(k)
            )
        except Exception as e:                                    # keyword search is only one half of RAG: never let it break an answer
            log.warning("library.keyword_search_failed error=%s", e.__class__.__name__)
            return []

"""Data access for the textbook library: `documents` (one per file) and `chunks` (passages for search)."""
from datetime import datetime, timezone

from bson import ObjectId


class LibraryRepository:
    def __init__(self, db):
        self.documents, self.chunks = db.documents, db.chunks

    def for_user(self, user_id: ObjectId) -> list[dict]:
        return list(self.documents.find({"user_id": user_id}).sort("created_at", -1))

    def add(self, user_id: ObjectId, name: str, pages: int, chunks: list[dict]) -> dict:
        doc = {"user_id": user_id, "name": name, "pages": pages, "chunks": len(chunks), "active": True, "created_at": datetime.now(timezone.utc)}
        doc["_id"] = self.documents.insert_one(doc).inserted_id
        self.chunks.insert_many([{"doc_id": doc["_id"], "user_id": user_id, **c} for c in chunks])
        return doc

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
        """MongoDB $text search over the given documents, best match first."""
        return list(
            self.chunks.find(
                {"$text": {"$search": query}, "doc_id": {"$in": doc_ids}},
                {"score": {"$meta": "textScore"}, "page": 1, "text": 1, "doc_id": 1},
            ).sort([("score", {"$meta": "textScore"})]).limit(k)
        )

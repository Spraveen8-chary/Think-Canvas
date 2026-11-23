"""Data access for canvases. Every query includes user_id, so one user can never touch another's data."""
from datetime import datetime, timezone

from bson import ObjectId


class CanvasRepository:
    def __init__(self, db):
        self.col = db.canvases

    def for_user(self, user_id: ObjectId) -> list[dict]:
        return list(self.col.find({"user_id": user_id}, {"title": 1, "updated_at": 1}).sort("updated_at", -1))

    def create(self, user_id: ObjectId, title: str) -> ObjectId:
        doc = {"user_id": user_id, "title": title, "items": [], "updated_at": datetime.now(timezone.utc)}
        return self.col.insert_one(doc).inserted_id

    def get(self, user_id: ObjectId, canvas_id: ObjectId) -> dict | None:
        return self.col.find_one({"_id": canvas_id, "user_id": user_id})

    def save(self, user_id: ObjectId, canvas_id: ObjectId, title: str, items: list) -> bool:
        r = self.col.update_one(
            {"_id": canvas_id, "user_id": user_id},
            {"$set": {"title": title, "items": items, "updated_at": datetime.now(timezone.utc)}},
        )
        return r.matched_count > 0

    def delete(self, user_id: ObjectId, canvas_id: ObjectId) -> bool:
        return self.col.delete_one({"_id": canvas_id, "user_id": user_id}).deleted_count > 0

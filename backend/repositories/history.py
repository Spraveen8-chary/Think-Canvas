"""Data access for the per-user history of questions and answers (no handwriting or image data)."""
from datetime import datetime, timezone

from bson import ObjectId


class HistoryRepository:
    def __init__(self, db):
        self.col = db.history

    def add(self, user_id: ObjectId, entry: dict) -> None:
        self.col.insert_one({"user_id": user_id, "ts": datetime.now(timezone.utc), **entry})

    def recent(self, user_id: ObjectId, limit: int) -> list[dict]:
        return list(self.col.find({"user_id": user_id}).sort("ts", -1).limit(limit))

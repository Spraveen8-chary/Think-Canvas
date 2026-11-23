"""Data access for imported images."""
from datetime import datetime, timezone

from bson import Binary, ObjectId


class AssetRepository:
    def __init__(self, db):
        self.col = db.assets

    def add(self, user_id: ObjectId, mime: str, data: bytes) -> ObjectId:
        doc = {"user_id": user_id, "mime": mime, "data": Binary(data), "created_at": datetime.now(timezone.utc)}
        return self.col.insert_one(doc).inserted_id

    def get(self, user_id: ObjectId, asset_id: ObjectId) -> dict | None:
        return self.col.find_one({"_id": asset_id, "user_id": user_id})

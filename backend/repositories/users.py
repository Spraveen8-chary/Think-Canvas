"""Data access for users and login sessions."""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ReturnDocument


class UserRepository:
    def __init__(self, db):
        self.users, self.sessions, self.reports = db.users, db.sessions, db.reports

    def by_email(self, email: str) -> dict | None:
        return self.users.find_one({"email": email})

    def by_id(self, user_id: ObjectId) -> dict | None:
        return self.users.find_one({"_id": user_id})

    def insert(self, user: dict) -> ObjectId:
        """Raises pymongo DuplicateKeyError when the email is already registered."""
        return self.users.insert_one(user).inserted_id

    def update_profile(self, user_id: ObjectId, changes: dict) -> None:
        self.users.update_one({"_id": user_id}, {"$set": changes})

    # sessions
    def add_session(self, token_hash: str, user_id: ObjectId, expires_at: datetime) -> None:
        self.sessions.insert_one({"token_hash": token_hash, "user_id": user_id, "expires_at": expires_at})

    def session(self, token_hash: str) -> dict | None:
        s = self.sessions.find_one({"token_hash": token_hash})
        if s and s["expires_at"].tzinfo is None:                 # some drivers return naive UTC
            s["expires_at"] = s["expires_at"].replace(tzinfo=timezone.utc)
        return s

    def delete_session(self, token_hash: str) -> None:
        self.sessions.delete_one({"token_hash": token_hash})

    # moderation: every violation is kept for review; at the limit the account is suspended
    def record_violation(self, user_id: ObjectId, entry: dict, limit: int) -> int:
        user = self.users.find_one_and_update({"_id": user_id}, {"$inc": {"violations": 1}}, return_document=ReturnDocument.AFTER)
        strikes = int((user or {}).get("violations", 1))
        self.reports.insert_one({**entry, "user_id": user_id, "strike": strikes})
        if strikes >= limit:
            self.users.update_one({"_id": user_id}, {"$set": {"suspended": True, "suspended_at": entry.get("ts")}})
        return strikes

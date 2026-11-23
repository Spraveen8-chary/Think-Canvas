"""MongoDB connection and indexes (the only place that knows how to connect).

Collections: users, sessions, canvases, assets, documents, chunks, history.
Repositories (backend/repositories) are the only code that queries them.
"""
import logging

from pymongo import ASCENDING, DESCENDING, TEXT, MongoClient

from .core.config import get_settings
from .core.logging import safe_host

log = logging.getLogger("tc.db")
_db = None


def set_db(db) -> None:
    """Use a given database (tests pass an in-memory one)."""
    global _db
    _db = db
    ensure_indexes(db)


def get_db():
    global _db
    if _db is None:
        s = get_settings()
        client = MongoClient(s.mongo_uri, serverSelectionTimeoutMS=3000)
        try:
            client.admin.command("ping")
        except Exception as e:
            raise RuntimeError(
                f"Cannot reach MongoDB at {safe_host(s.mongo_uri)} ({e.__class__.__name__}).\n"
                "Start one with:  docker run -d --name think-canvas-mongo -p 27017:27017 mongo:8"
            ) from e
        log.info("mongo.connected host=%s db=%s", safe_host(s.mongo_uri), s.mongo_db)
        set_db(client[s.mongo_db])
    return _db


def ping() -> bool:
    try:
        get_db().command("ping")
        return True
    except Exception:
        return False


def ensure_indexes(db) -> None:
    db.users.create_index("email", unique=True)
    db.sessions.create_index("token_hash", unique=True)
    db.sessions.create_index("expires_at", expireAfterSeconds=0)        # expired sessions delete themselves
    db.canvases.create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    db.documents.create_index("user_id")
    db.chunks.create_index("doc_id")
    db.history.create_index([("user_id", ASCENDING), ("ts", DESCENDING)])
    try:
        db.chunks.create_index([("text", TEXT)], default_language="english")    # RAG keyword search
    except Exception:
        log.debug("text index not created (in-memory test database)")

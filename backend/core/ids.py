from bson import ObjectId

from .errors import NotFound


def object_id(value: str) -> ObjectId:
    """Parses an id from a URL. A malformed id is simply 'not found'."""
    try:
        return ObjectId(value)
    except Exception:
        raise NotFound("Not found")

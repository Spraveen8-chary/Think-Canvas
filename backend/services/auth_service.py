"""Accounts and sessions: the rules (valid email, password length, who may log in)."""
import logging
import re
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from ..core import security
from ..core.errors import BadRequest, Conflict, Unauthorized
from ..core.logging import kv, mask_email
from ..repositories.users import UserRepository

log = logging.getLogger("tc.auth")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_DAYS = 30


class AuthService:
    def __init__(self, users: UserRepository):
        self.users = users

    def register(self, name: str, email: str, password: str, organisation: str = "") -> tuple[dict, str, datetime]:
        email, name = email.strip().lower(), name.strip()
        if not name:
            raise BadRequest("Please enter your name")
        if not EMAIL_RE.match(email):
            raise BadRequest("Please enter a valid email address")
        if len(password) < 8:
            raise BadRequest("Password must be at least 8 characters")
        user = {
            "name": name[:80], "email": email, "organisation": organisation.strip()[:120],
            "password_hash": security.hash_password(password), "created_at": datetime.now(timezone.utc),
        }
        try:
            user["_id"] = self.users.insert(user)
        except DuplicateKeyError:
            raise Conflict("An account with this email already exists")
        log.info("auth.register %s", kv(user=user["_id"], email=mask_email(email)))
        return (user, *self._new_session(user))

    def login(self, email: str, password: str) -> tuple[dict, str, datetime]:
        email = email.strip().lower()
        user = self.users.by_email(email)
        if not user or not security.verify_password(password, user["password_hash"]):
            log.warning("auth.login_failed %s", kv(email=mask_email(email)))
            raise Unauthorized("Wrong email or password")
        log.info("auth.login %s", kv(user=user["_id"]))
        return (user, *self._new_session(user))

    def logout(self, token: str | None) -> None:
        if token:
            self.users.delete_session(security.token_digest(token))

    def user_for_token(self, token: str | None) -> dict | None:
        session = token and self.users.session(security.token_digest(token))
        if not session or session["expires_at"] <= datetime.now(timezone.utc):
            return None
        return self.users.by_id(session["user_id"])

    def update_profile(self, user: dict, name: str, organisation: str) -> dict:
        changes = {"name": name.strip()[:80] or user["name"], "organisation": organisation.strip()[:120]}
        self.users.update_profile(user["_id"], changes)
        return {**user, **changes}

    def _new_session(self, user: dict) -> tuple[str, datetime]:
        token = security.new_token()
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        self.users.add_session(security.token_digest(token), user["_id"], expires)
        return token, expires

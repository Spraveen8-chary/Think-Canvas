"""Passwords and session tokens.

Passwords: salted scrypt (memory-hard), compared in constant time. Plain passwords are never stored.
Sessions: a random token goes into an HttpOnly cookie; only its SHA-256 is stored in MongoDB, so a
database leak does not leak usable logins.
"""
import hashlib
import hmac
import secrets

_SCRYPT = dict(n=2**14, r=8, p=1)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
        return hmac.compare_digest(check.hex(), digest)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

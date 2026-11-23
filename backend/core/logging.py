"""Logging: one readable line per event, to the console and to logs/think-canvas.log (rotated).

    2026-11-23 13:40:02 INFO  tc.ask      [a1b2c3d4] ask.done user=64f.. provider=openrouter tokens_in=412 tokens_out=88 ms=2140

Rules that keep the logs clean and safe:
  * every line carries the request id, so one request can be followed end to end
  * events are `name key=value ...` (see `kv`) so they are easy to read and to grep
  * secrets, passwords, prompts, handwriting and image data are NEVER logged: `kv` drops them
"""
import logging
import re
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from .config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_FORMAT = "%(asctime)s %(levelname)-5s %(name)-11s [%(request_id)s] %(message)s"
# A field is dropped when its WHOLE name (or its last word) is one of these: api_key, password, image...
# ("tokens_in" and "typed_chars" are fine: they are counts, not content).
_FORBIDDEN = re.compile(r"^(.*_)?(key|token|secret|password|authorization|cookie|image|prompt|typed|text)$", re.I)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    if getattr(root, "_tc_configured", False):
        return
    root.setLevel(settings.log_level)
    formatter = logging.Formatter(_FORMAT, "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(settings.log_dir / "think-canvas.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass                                              # read-only disk: console only
    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(_RequestIdFilter())
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "pymongo", "multipart", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True   # our own request line replaces it
    root._tc_configured = True


def _value(v) -> str:
    s = str(v)
    return f'"{s}"' if (" " in s or not s) else s


def kv(**fields) -> str:
    """`key=value` pairs for a log line. Sensitive-looking keys are dropped, None is skipped."""
    return " ".join(f"{k}={_value(v)}" for k, v in fields.items() if v is not None and not _FORBIDDEN.search(k))


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def safe_host(uri: str) -> str:
    """mongodb://user:pass@host:27017 -> host:27017 (never log credentials)."""
    p = urlparse(uri)
    return f"{p.hostname}:{p.port}" if p.hostname and p.port else (p.hostname or "unknown")

"""Cross-cutting HTTP concerns, applied to every request in one place:
request id + access log, browser security headers, and a same-origin check for writes."""
import logging
import time
import uuid
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .logging import kv, request_id_var

log = logging.getLogger("tc.http")

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' wss://streaming.assemblyai.com wss://generativelanguage.googleapis.com; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Gives each request an id (shown in every log line and returned as X-Request-ID) and logs it."""

    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        request_id_var.set(rid)
        started = time.perf_counter()
        response = await call_next(request)
        ms = round((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = rid
        is_api = request.url.path.startswith("/api")
        log.log(
            logging.INFO if is_api else logging.DEBUG,                       # static files stay quiet
            "http %s", kv(method=request.method, path=request.url.path, status=response.status_code, ms=ms),
        )
        return response


class SecurityMiddleware(BaseHTTPMiddleware):
    """Blocks cross-site writes (a page on another website cannot act as the logged-in user)
    and adds defensive headers."""

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in WRITE_METHODS and origin and urlparse(origin).netloc != request.headers.get("host"):
            log.warning("blocked cross-origin write %s", kv(method=request.method, path=request.url.path))
            return JSONResponse({"error": {"code": "forbidden", "message": "Cross-site request blocked"}}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith("/api"):          # page, scripts, styles: always re-check, so updates show up
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

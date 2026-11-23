"""One error vocabulary for the whole backend.

Services and repositories raise `AppError` subclasses; they never build HTTP responses.
`install_error_handlers` turns them into a single JSON shape the frontend can rely on:
    {"error": {"code": "not_found", "message": "Not found"}}
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("tc.app")


class AppError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str = "Something went wrong", *, headers: dict | None = None):
        super().__init__(message)
        self.message = message
        self.headers = headers or {}


class BadRequest(AppError): status, code = 400, "bad_request"
class Unauthorized(AppError): status, code = 401, "unauthorized"
class Forbidden(AppError): status, code = 403, "forbidden"
class NotFound(AppError): status, code = 404, "not_found"
class Conflict(AppError): status, code = 409, "conflict"
class TooLarge(AppError): status, code = 413, "too_large"
class RateLimited(AppError): status, code = 429, "rate_limited"
class UpstreamError(AppError): status, code = 502, "upstream_error"           # the AI provider failed


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        if exc.status >= 500:
            log.warning("request.failed code=%s message=%s", exc.code, exc.message)
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(_body("invalid_request", f"{where}: {first.get('msg', 'invalid value')}".strip(": ")), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("request.crashed path=%s", request.url.path)        # full traceback goes to the log only
        return JSONResponse(_body("internal_error", "Something went wrong on the server"), status_code=500)

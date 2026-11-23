"""Dependency injection: how a route gets what it needs.

Routes never build repositories or services themselves; they ask for them here. That keeps routes
thin, makes every layer replaceable in tests, and gives one place to see how the app is wired.
"""
from fastapi import Depends, Request

from ..core.config import Settings, get_settings
from ..core.errors import Unauthorized
from ..core.ratelimit import RateLimiter
from ..db import get_db
from ..repositories.assets import AssetRepository
from ..repositories.canvases import CanvasRepository
from ..repositories.history import HistoryRepository
from ..repositories.library import LibraryRepository
from ..repositories.users import UserRepository
from ..services.assistant import Assistant
from ..services.auth_service import AuthService
from ..services.library_service import LibraryService
from ..services.llm import registry

COOKIE = "tc_session"

_settings = get_settings()
auth_limiter = RateLimiter(_settings.auth_rate_per_min, label="login attempts")
ask_limiter = RateLimiter(_settings.ask_rate_per_min, label="AI requests")


def settings() -> Settings:
    return get_settings()


# ---- repositories ---------------------------------------------------------------------
def canvas_repo(db=Depends(get_db)) -> CanvasRepository: return CanvasRepository(db)
def asset_repo(db=Depends(get_db)) -> AssetRepository: return AssetRepository(db)
def history_repo(db=Depends(get_db)) -> HistoryRepository: return HistoryRepository(db)
def library_repo(db=Depends(get_db)) -> LibraryRepository: return LibraryRepository(db)


# ---- services -------------------------------------------------------------------------
def auth_service(db=Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db))


def library_service(repo: LibraryRepository = Depends(library_repo)) -> LibraryService:
    return LibraryService(repo)


def assistant(library: LibraryService = Depends(library_service)) -> Assistant:
    return Assistant(registry.get_provider(), library)


# ---- who is calling -------------------------------------------------------------------
def current_user(request: Request, auth: AuthService = Depends(auth_service)) -> dict:
    user = auth.user_for_token(request.cookies.get(COOKIE))
    if not user:
        raise Unauthorized("Please log in")
    return user


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"

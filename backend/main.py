"""Think Canvas backend: builds the FastAPI app. Run with:  python -m backend

Layers (each only calls the one below it):
    api/routes  ->  services  ->  repositories  ->  db (MongoDB)
                       \\-> services/llm (AI providers)
    core/ holds the cross-cutting pieces: settings, logging, errors, security, rate limits, middleware.
See docs/ARCHITECTURE.md.
"""
import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import ask, assets, auth, canvases, health, library, live, stt
from .core.config import FRONTEND, get_settings
from .core.errors import install_error_handlers
from .core.logging import kv, safe_host, setup_logging
from .core.middleware import RequestContextMiddleware, SecurityMiddleware
from .db import get_db
from .services.llm import registry

# Windows can map .js to text/plain, which breaks ES modules in the browser.
mimetypes.add_type("text/javascript", ".js")
log = logging.getLogger("tc.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    get_db()                                             # connect now, so a missing database is reported at start-up
    provider = registry.get_provider()
    log.info("startup %s", kv(
        provider=provider.name, model=provider.model, mongo=safe_host(s.mongo_uri), db=s.mongo_db,
        port=s.port, log_file=s.log_dir / "think-canvas.log",
    ))
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    setup_logging(get_settings())
    app = FastAPI(title="Think Canvas", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(RequestContextMiddleware)          # added last = outermost: it sees every request
    install_error_handlers(app)
    for module in (health, auth, canvases, assets, library, ask, stt, live):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
    return app


app = create_app()

"""Liveness/readiness check: is the server up, and can it reach MongoDB?"""
from fastapi import APIRouter

from ...db import ping

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok" if ping() else "degraded", "database": ping()}

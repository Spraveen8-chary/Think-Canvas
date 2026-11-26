"""Gemini Live Session HTTP routes: ephemeral token, canvas tool validation, history."""
import asyncio

from fastapi import APIRouter, Depends

from ...core.config import Settings
from ...core.logging import kv
from ...repositories.history import HistoryRepository
from ...services import live as live_service
from ...services.prompts import LIVE_TUTOR_INSTRUCTION
from ..deps import current_user, history_repo, live_limiter, settings
from ..schemas import LiveBlockIn, LiveHistoryIn

router = APIRouter(prefix="/api/live", tags=["live"])


@router.post("/token")
async def create_live_token(user: dict = Depends(current_user), s: Settings = Depends(settings)):
    live_limiter.check(str(user["_id"]))
    result = await live_service.mint_live_token(s.gemini_api_key, s.gemini_live_model, LIVE_TUTOR_INSTRUCTION)
    live_service.log.info("live.token %s", kv(user=str(user["_id"])[:4], model=s.gemini_live_model))
    return result


@router.post("/blocks")
def validate_live_block(body: LiveBlockIn, user: dict = Depends(current_user)):
    return live_service.validate_tool_block(body.name, body.args)


@router.post("/history")
async def save_live_history(
    body: LiveHistoryIn,
    user: dict = Depends(current_user),
    history: HistoryRepository = Depends(history_repo),
):
    first_user = next((m.get("text", "") for m in body.transcript if m.get("role") == "user" and m.get("text")), "")
    last_model = next((m.get("text", "") for m in reversed(body.transcript) if m.get("role") == "model" and m.get("text")), "")
    summary = " | ".join(f"{m.get('role', '')}: {str(m.get('text', ''))[:120]}" for m in body.transcript[:8])
    await asyncio.to_thread(history.add, user["_id"], {
        "canvas_id": body.canvas_id,
        "mode": "live",
        "read": f"[Live] {first_user[:160]}" if first_user else "[Live Session]",
        "kinds": body.kinds[:50],
        "answer": (last_model or summary)[:300],
        "sources": [],
        "tokens": None,
    })
    return {"ok": True}

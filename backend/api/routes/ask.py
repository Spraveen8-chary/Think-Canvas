"""Ask the AI about the newest writing / typed text / image, and read back past answers."""
import asyncio

from fastapi import APIRouter, Depends

from ...core.config import Settings
from ...core.errors import BadRequest
from ...repositories.history import HistoryRepository
from ...services.assistant import Assistant
from ..deps import ask_limiter, assistant, current_user, history_repo, settings
from ..schemas import AskIn

router = APIRouter(prefix="/api", tags=["ask"])


@router.get("/config")
def get_config(s: Settings = Depends(settings)):
    return {
        "provider": s.provider,
        "autoAskDelayMs": s.auto_ask_delay_ms,
        "sttAutosubmitSilenceMs": s.stt_autosubmit_silence_ms,
    }


@router.post("/ask")
async def ask(body: AskIn, user: dict = Depends(current_user), ai: Assistant = Depends(assistant),
              history: HistoryRepository = Depends(history_repo)):
    if not body.image and not body.typed.strip():
        raise BadRequest("Nothing to answer")
    if body.image and not body.image.startswith("data:image/"):
        raise BadRequest("Bad image")
    ask_limiter.check(str(user["_id"]))
    result = await ai.answer(user["_id"], body.image, body.typed.strip(), body.use_library)
    first_text = next((b["text"] for b in result.blocks if b["t"] == "text"), "")
    await asyncio.to_thread(history.add, user["_id"], {
        "canvas_id": body.canvas_id, "read": result.read, "kinds": [b["t"] for b in result.blocks],
        "answer": first_text[:300], "sources": result.sources, "tokens": result.tokens,
    })
    return {"read": result.read, "blocks": result.blocks, "tokens": result.tokens, "sources": result.sources}


@router.get("/history")
def recent_history(limit: int = 50, user: dict = Depends(current_user), repo: HistoryRepository = Depends(history_repo)):
    return [{
        "id": str(r["_id"]), "ts": r["ts"].isoformat(), "read": r["read"], "kinds": r["kinds"],
        "answer": r["answer"], "sources": r.get("sources", []), "tokens": r.get("tokens"),
    } for r in repo.recent(user["_id"], max(1, min(limit, 200)))]

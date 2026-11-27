"""Ask the AI about the newest writing / typed text / image, and read back past answers."""
import asyncio

from fastapi import APIRouter, Depends

from ...core.config import Settings
from ...core.errors import BadRequest
from ...repositories.history import HistoryRepository
from ...services import moderation
from ...services.assistant import Assistant
from ...services.moderation import ModerationService
from ..deps import ask_limiter, assistant, current_user, history_repo, moderation_service, settings
from ..schemas import AskIn

router = APIRouter(prefix="/api", tags=["ask"])


@router.get("/config")
def get_config(s: Settings = Depends(settings)):
    return {
        "provider": s.provider,
        "autoAskDelayMs": s.auto_ask_delay_ms,
        "sttAutosubmitSilenceMs": s.stt_autosubmit_silence_ms,
    }


def _violation(payload: dict) -> dict:
    """The browser shows a warning pop-up for this and removes what the student wrote."""
    return {"read": "", "blocks": [], "tokens": {"in": 0, "out": 0}, "sources": [], "violation": payload}


@router.post("/ask")
async def ask(body: AskIn, user: dict = Depends(current_user), ai: Assistant = Depends(assistant),
              history: HistoryRepository = Depends(history_repo), mod: ModerationService = Depends(moderation_service)):
    if not body.image and not body.typed.strip():
        raise BadRequest("Nothing to answer")
    if body.image and not body.image.startswith("data:image/"):
        raise BadRequest("Bad image")
    ask_limiter.check(str(user["_id"]))
    typed = body.typed.strip()
    source = body.source or ("handwriting" if body.image and not typed else "type")

    hit = moderation.scan(typed)                                   # bad language is stopped before it reaches the AI
    if hit:
        return _violation(await asyncio.to_thread(mod.report, user, source, hit.category, typed))

    memory = await asyncio.to_thread(history.conversation, user["_id"], body.canvas_id, 4)        # earlier turns of this canvas
    result = await ai.answer(user["_id"], body.image, typed, body.use_library, memory=memory, earlier=body.earlier.strip(), grey_ink=body.grey_ink)

    hit = moderation.scan(result.read)                            # handwriting: check the text the AI read from the picture
    if hit or result.flag == "abuse":
        category = hit.category if hit else "abuse"
        return _violation(await asyncio.to_thread(mod.report, user, source, category, result.read or "(handwriting)"))

    texts = [b["text"] for b in result.blocks if b["t"] == "text"]
    if not result.flag:                                           # off-topic replies are not remembered as part of the study conversation
        await asyncio.to_thread(history.add, user["_id"], {
            "canvas_id": body.canvas_id, "read": result.read, "kinds": [b["t"] for b in result.blocks],
            "answer": (texts[0] if texts else "")[:300], "answer_full": " ".join(texts)[:900],
            "sources": result.sources, "tokens": result.tokens,
        })
    return {"read": result.read, "blocks": result.blocks, "tokens": result.tokens, "sources": result.sources,
            "flag": result.flag, "conf": result.conf}


@router.get("/history")
def recent_history(limit: int = 50, user: dict = Depends(current_user), repo: HistoryRepository = Depends(history_repo)):
    return [{
        "id": str(r["_id"]), "ts": r["ts"].isoformat(), "read": r["read"], "kinds": r["kinds"],
        "answer": r["answer"], "sources": r.get("sources", []), "tokens": r.get("tokens"),
    } for r in repo.recent(user["_id"], max(1, min(limit, 200)))]

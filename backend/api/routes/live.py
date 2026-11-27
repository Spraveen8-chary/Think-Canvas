"""Gemini Live Session: WebSocket relay to Gemini, canvas tool validation, history."""
import asyncio
import json
from urllib.parse import urlparse

import websockets
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from ...core.config import get_settings
from ...core.errors import RateLimited
from ...db import get_db
from ...repositories.users import UserRepository
from ...services import moderation
from ...services.auth_service import AuthService
from ...services.moderation import ModerationService
from ...repositories.history import HistoryRepository
from ...services import live as live_service
from ...services.prompts import LIVE_TUTOR_INSTRUCTION
from ..deps import COOKIE, current_user, history_repo, live_limiter
from ..schemas import LiveBlockIn, LiveHistoryIn

router = APIRouter(prefix="/api/live", tags=["live"])


@router.websocket("/ws")
async def live_socket(ws: WebSocket):
    """Relays one voice session between the browser and Gemini Live. The API key and the session
    setup (model, tutor prompt, canvas tools) stay on the server; the browser only sends audio."""
    s = get_settings()
    await ws.accept()                                          # accept first: a refusal before this reaches the browser as a bare "1006"
    origin = ws.headers.get("origin")
    if origin and urlparse(origin).netloc != ws.headers.get("host"):
        await ws.close(code=1008, reason="Cross-site request blocked")
        return
    user = AuthService(UserRepository(get_db())).user_for_token(ws.cookies.get(COOKIE))
    if not user:
        await ws.close(code=1008, reason="Please log in")
        return
    if user.get("suspended"):
        await ws.close(code=1008, reason="Your account is suspended for repeated policy violations.")
        return
    if not s.gemini_api_key:
        await ws.close(code=1011, reason="Live Session is not configured (missing GEMINI_API_KEY)")
        return
    try:
        live_limiter.check(str(user["_id"]))
    except RateLimited:
        await ws.close(code=1013, reason="Too many live sessions. Try again shortly.")
        return

    try:
        start = json.loads(await asyncio.wait_for(ws.receive_text(), 10))      # {"start": true, "resumeHandle": "..."}
    except Exception:
        await ws.close(code=1002, reason="Expected a start message")
        return
    handle = start.get("resumeHandle") if isinstance(start.get("resumeHandle"), str) else None
    language = start.get("language") if start.get("language") in live_service.LANGUAGES else "en"
    mod = ModerationService(UserRepository(get_db()))

    live_service.log.info("live.session user=%s model=%s", str(user["_id"])[:4], s.gemini_live_model)
    try:
        async with websockets.connect(
            live_service.LIVE_WS_URL, additional_headers={"x-goog-api-key": s.gemini_api_key}, max_size=None,
        ) as gem:
            await gem.send(json.dumps(live_service.build_setup(s.gemini_live_model, LIVE_TUTOR_INSTRUCTION, handle, language)))

            async def up():                                   # browser -> Gemini (audio, text, tool results)
                while True:
                    msg = await ws.receive_text()
                    if '"setup"' in msg[:20]:                  # the browser may never change the session setup
                        continue
                    await gem.send(msg)

            async def down():                                 # Gemini -> browser
                heard = ""                                    # what the student said recently, for the language check
                async for msg in gem:
                    text = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
                    if '"inputTranscription"' in text:
                        try:
                            heard = (heard + (json.loads(text)["serverContent"]["inputTranscription"].get("text") or ""))[-300:]
                        except (KeyError, TypeError, ValueError):
                            pass
                        hit = moderation.scan(heard)
                        if hit:                               # bad language in the student's speech: warn, report, end the session
                            payload = await asyncio.to_thread(mod.report, user, "voice", hit.category, heard)
                            await ws.send_text(json.dumps({"tcViolation": payload}))
                            return
                    await ws.send_text(text)

            tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
            done, pending = await asyncio.wait(tasks, timeout=live_service.MAX_SESSION_S, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except websockets.ConnectionClosed as e:
        reason = (e.reason or "Gemini closed the session")[:120]
        live_service.log.warning("live.gemini_closed code=%s reason=%s", e.code, reason)
        await _close(ws, 1011, f"Gemini: {reason} (code {e.code})")
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as e:                                     # network / handshake failure; never leak details
        live_service.log.warning("live.relay_error err=%s", e.__class__.__name__)
        await _close(ws, 1011, "Could not reach Gemini Live")
    else:
        await _close(ws, 1000, "Session ended")


async def _close(ws: WebSocket, code: int, reason: str):
    try:
        await ws.close(code=code, reason=reason[:120])
    except Exception:
        pass


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

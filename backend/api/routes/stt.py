"""Speech-to-text HTTP routes: temporary AssemblyAI token and pre-recorded fallback."""
from fastapi import APIRouter, Depends, File, Form, UploadFile

from ...core.config import Settings
from ...core.logging import kv
from ...services import stt as stt_service
from ..deps import current_user, settings, stt_limiter

router = APIRouter(prefix="/api/stt", tags=["stt"])


@router.post("/token")
async def create_stt_token(user: dict = Depends(current_user), s: Settings = Depends(settings)):
    stt_limiter.check(str(user["_id"]))
    result = await stt_service.mint_streaming_token(s.assemblyai_api_key)
    stt_service.log.info("stt.token %s", kv(user=str(user["_id"])[:4]))
    return result


@router.post("/transcribe")
async def transcribe_fallback(
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    user: dict = Depends(current_user),
    s: Settings = Depends(settings),
):
    stt_limiter.check(str(user["_id"]))
    data = await file.read()
    stt_service.validate_audio_upload(file.content_type or "", len(data))
    result = await stt_service.transcribe_audio(s.assemblyai_api_key, data, language_code=language.strip() or "auto")
    stt_service.log.info("stt.transcribe %s", kv(user=str(user["_id"])[:4], lang=result["language_code"]))
    return result

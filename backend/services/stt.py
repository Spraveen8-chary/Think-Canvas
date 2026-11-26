"""AssemblyAI speech-to-text service: temporary streaming tokens and pre-recorded fallback."""
import asyncio
import logging
import time

import httpx

from ..core.errors import BadRequest, RateLimited, TooLarge, UpstreamError

log = logging.getLogger("tc.stt")

STREAMING_TOKEN_URL = "https://streaming.assemblyai.com/v3/token"
STREAMING_WS_URL = "wss://streaming.assemblyai.com/v3/ws"
UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

MAX_AUDIO_BYTES = 15 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/webm", "video/webm", "audio/ogg", "audio/mp4",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
}


def _require_key(api_key: str) -> str:
    if not api_key:
        raise BadRequest("Speech-to-text is not configured (missing ASSEMBLYAI_API_KEY)")
    return api_key


def _map_http_error(status: int, action: str) -> UpstreamError | RateLimited:
    log.warning("stt.vendor_error action=%s status=%s", action, status)
    if status == 429:
        return RateLimited("Speech-to-text rate limit reached. Try again shortly.")
    return UpstreamError("Speech-to-text service is unavailable right now")


async def mint_streaming_token(api_key: str, *, expires_in_seconds: int = 300) -> dict:
    """Mint a short-lived AssemblyAI v3 streaming token for direct browser WebSocket use."""
    key = _require_key(api_key)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                STREAMING_TOKEN_URL,
                params={"expires_in_seconds": expires_in_seconds},
                headers={"Authorization": key},
            )
    except httpx.HTTPError as e:
        log.warning("stt.token_network_error err=%s", e.__class__.__name__)
        raise UpstreamError("Could not reach speech-to-text service") from e

    if res.status_code >= 400:
        raise _map_http_error(res.status_code, "token")

    token = res.json().get("token")
    if not token:
        raise UpstreamError("Speech-to-text service returned an invalid token")
    return {"token": token, "ws_url": STREAMING_WS_URL, "expires_in": expires_in_seconds}


def validate_audio_upload(content_type: str, size: int) -> None:
    """Validate uploaded audio MIME type and byte length."""
    base_type = (content_type or "").split(";", 1)[0].strip().lower()
    if base_type not in ALLOWED_AUDIO_TYPES:
        raise BadRequest("Unsupported audio format")
    if size <= 0:
        raise BadRequest("Audio recording is empty")
    if size > MAX_AUDIO_BYTES:
        raise TooLarge("Audio recording is too large (max 15 MB)")


async def transcribe_audio(
    api_key: str,
    audio_bytes: bytes,
    *,
    language_code: str = "auto",
    poll_interval_s: float = 1.0,
    timeout_s: float = 60.0,
) -> dict:
    """Upload audio to AssemblyAI v2 and poll until pre-recorded transcription completes."""
    key = _require_key(api_key)
    if not audio_bytes:
        raise BadRequest("Audio recording is empty")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise TooLarge("Audio recording is too large (max 15 MB)")

    headers = {"Authorization": key}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            up = await client.post(
                UPLOAD_URL,
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=audio_bytes,
            )
            if up.status_code >= 400:
                raise _map_http_error(up.status_code, "upload")
            upload_url = up.json().get("upload_url")
            if not upload_url:
                raise UpstreamError("Speech-to-text upload failed")

            payload: dict = {"audio_url": upload_url}
            if not language_code or language_code == "auto":
                payload["language_detection"] = True
            else:
                payload["language_code"] = language_code

            job = await client.post(TRANSCRIPT_URL, headers=headers, json=payload)
            if job.status_code >= 400:
                raise _map_http_error(job.status_code, "create")
            tid = job.json().get("id")
            if not tid:
                raise UpstreamError("Speech-to-text job could not start")

            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                poll = await client.get(f"{TRANSCRIPT_URL}/{tid}", headers=headers)
                if poll.status_code >= 400:
                    raise _map_http_error(poll.status_code, "poll")
                data = poll.json()
                status = data.get("status")
                if status == "completed":
                    return {
                        "text": (data.get("text") or "").strip(),
                        "language_code": data.get("language_code") or language_code or "auto",
                    }
                if status == "error":
                    log.warning("stt.job_failed tid=%s", tid)
                    raise UpstreamError("Speech-to-text transcription failed")
                await asyncio.sleep(poll_interval_s)
    except httpx.HTTPError as e:
        log.warning("stt.transcribe_network_error err=%s", e.__class__.__name__)
        raise UpstreamError("Could not reach speech-to-text service") from e

    raise UpstreamError("Speech-to-text transcription timed out")

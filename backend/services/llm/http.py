"""POST JSON to an AI API with a timeout and a few retries for temporary failures (429 / 5xx / network)."""
import asyncio
import logging

import httpx

from ...core.logging import kv
from .base import LLMError

log = logging.getLogger("tc.llm")
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF_S = (0.6, 1.8)                       # two retries, then give up


async def post_json(url: str, headers: dict, body: dict, timeout_s: float, provider: str) -> dict:
    last = "no response"
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                r = await client.post(url, headers={"content-type": "application/json", **headers}, json=body)
        except httpx.TransportError as e:
            last = e.__class__.__name__
        else:
            if r.status_code < 400:
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code in (401, 403):
                raise LLMError(f"{provider} rejected the API key. Check it in the .env file.")
            if r.status_code not in RETRY_STATUS:
                # Provider error text is useful ("model not found") and does not contain our request.
                raise LLMError(f"{provider} error ({r.status_code}): {r.text[:200]}")
        if attempt < len(BACKOFF_S):
            log.warning("llm.retry %s", kv(provider=provider, attempt=attempt + 1, reason=last))
            await asyncio.sleep(BACKOFF_S[attempt])
    raise LLMError(f"{provider} is not responding ({last}). Please try again.")

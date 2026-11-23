"""One request from the canvas -> one (rarely two) AI calls -> validated blocks.

Token-saving rules (this is the "AI engineering" part):
  * only the newest writing is sent, as a small picture; typed text is sent as plain text (no picture)
  * a typed question searches the textbook first, so one call is enough
  * a handwritten question costs a second, text-only call only when the AI asks for a lookup
  * the system prompt is short, the reply is compact JSON, capped by MAX_OUTPUT_TOKENS
  * no conversation history is sent: each request stands alone
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from bson import ObjectId

from ..core.errors import UpstreamError
from ..core.logging import kv
from . import blocks, prompts
from .library_service import LibraryService
from .llm import LLMError, LLMProvider, LLMReply

log = logging.getLogger("tc.ask")


@dataclass
class Answer:
    read: str
    blocks: list[dict]
    tokens: dict = field(default_factory=lambda: {"in": 0, "out": 0})
    sources: list[str] = field(default_factory=list)


def _user_text(typed: str, excerpts: list[dict], has_image: bool) -> str:
    parts = []
    if typed:
        parts.append(f"Typed: {typed}")
    if excerpts:
        parts.append("Excerpts:\n" + "\n".join(f"[{e['source']} p.{e['page']}] {e['text']}" for e in excerpts))
    if not parts and has_image:
        parts.append("Read the image and answer.")
    return "\n".join(parts)


class Assistant:
    def __init__(self, provider: LLMProvider, library: LibraryService):
        self.provider, self.library = provider, library

    async def _ask(self, system: str, text: str, image: str | None) -> tuple[dict, LLMReply]:
        try:
            reply = await self.provider.complete(system, text, image)
            return blocks.sanitize(blocks.extract_json(reply.text)), reply
        except LLMError as e:
            raise UpstreamError(str(e))
        except ValueError as e:                                        # includes JSON errors
            log.warning("ask.unparsable_reply %s", kv(provider=self.provider.name, error=e))
            raise UpstreamError("The AI reply could not be understood. Please try again.")

    async def answer(self, user_id: ObjectId, image: str | None, typed: str, use_library: bool) -> Answer:
        started = time.perf_counter()
        library = use_library and await asyncio.to_thread(self.library.has_active, user_id)
        excerpts = await asyncio.to_thread(self.library.search, user_id, typed) if library and typed else []
        can_lookup = library and not excerpts and not typed
        out = Answer("", [])
        calls = 0

        def count(reply: LLMReply):
            out.tokens["in"] += reply.tokens_in
            out.tokens["out"] += reply.tokens_out

        result, reply = await self._ask(prompts.system_prompt(has_excerpts=bool(excerpts), can_lookup=can_lookup, animation=prompts.wants_animation(typed, bool(image))), _user_text(typed, excerpts, bool(image)), image)
        count(reply)
        calls += 1

        if result["lookup"] and can_lookup:                            # second pass: text only, with excerpts
            question = result["read"] or result["lookup"]
            excerpts = await asyncio.to_thread(self.library.search, user_id, f"{question} {result['lookup']}")
            if excerpts:
                result, reply = await self._ask(prompts.system_prompt(has_excerpts=True, animation=prompts.wants_animation(question, False)), _user_text(question, excerpts, False), None)
                count(reply)
                calls += 1

        out.read, out.blocks = result["read"], result["blocks"]
        out.sources = sorted({f"{e['source']} p.{e['page']}" for e in excerpts})
        log.info("ask.done %s", kv(
            user=user_id, provider=self.provider.name, model=reply.model or self.provider.model, calls=calls,
            has_picture=bool(image), typed_chars=len(typed), tokens_in=out.tokens["in"], tokens_out=out.tokens["out"],
            blocks=",".join(b["t"] for b in out.blocks) or "none", sources=len(out.sources), ms=round((time.perf_counter() - started) * 1000),
        ))
        return out

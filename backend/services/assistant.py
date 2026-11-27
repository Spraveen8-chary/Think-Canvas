"""One request from the canvas -> one (rarely two) AI calls -> validated blocks.

Token-saving rules (this is the "AI engineering" part):
  * only the newest writing is sent, as a small picture; typed text is sent as plain text (no picture)
  * a typed question searches the textbook first, so one call is enough
  * a handwritten question costs a second, text-only call only when the AI asks for a lookup
  * the system prompt is short, the reply is compact JSON, capped by MAX_OUTPUT_TOKENS

Memory (so a follow-up is understood): the last few question/answer turns of the SAME canvas are sent as a short
"Conversation so far", typed text that was already answered is sent as "Earlier", and already-answered handwriting
is drawn grey in the picture. The AI answers only the new part, with that context. A new canvas starts fresh.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

from bson import ObjectId

from ..core.errors import UpstreamError
from ..core.logging import kv
from . import blocks, moderation, prompts
from .library_service import LibraryService
from .llm import LLMError, LLMProvider, LLMReply

log = logging.getLogger("tc.ask")
RETRY_HINT = "\n(Your previous reply was not valid JSON. Reply again with ONE valid JSON object only, literal numbers only.)"


@dataclass
class Answer:
    read: str
    blocks: list[dict]
    tokens: dict = field(default_factory=lambda: {"in": 0, "out": 0})
    sources: list[str] = field(default_factory=list)
    flag: str | None = None                     # "off_topic" | "abuse" (set by the AI), see services/moderation.py
    conf: float | None = None                   # how sure the AI is that it read the handwriting correctly


MEMORY_TURNS = 4            # how many earlier turns of this canvas are remembered
MEMORY_ANSWER_CHARS = 350   # each remembered answer is trimmed: this is what costs tokens


def _memory_text(turns: list[dict]) -> str:
    """The "Conversation so far" text for the prompt, oldest first. Short on purpose."""
    lines = []
    for i, t in enumerate(turns, 1):
        question = (t.get("read") or "").strip()[:200] or "(a drawing)"
        answer = (t.get("answer_full") or t.get("answer") or "").strip()[:MEMORY_ANSWER_CHARS]
        drew = sorted({k for k in t.get("kinds", []) if k != "text"})
        lines.append(f"Q{i}: {question}" + chr(10) + f"A{i}: {answer}" + (f" [also drew: {', '.join(drew)}]" if drew else ""))
    return "Conversation so far (oldest first):" + chr(10) + chr(10).join(lines) if lines else ""


def _user_text(typed: str, excerpts: list[dict], has_image: bool, memory: str = "", earlier: str = "") -> str:
    parts = []
    if memory:
        parts.append(memory)
    if earlier:
        parts.append(f"Earlier (already answered): {earlier}")
    if typed:
        parts.append(f"Typed: {typed}")
    if excerpts:
        parts.append("Excerpts:\n" + "\n".join(f"[{e['source']} p.{e['page']}] {e['text']}" for e in excerpts))
    if has_image and not typed:
        parts.append("Read the image and answer the new (black) writing." if memory or earlier else "Read the image and answer.")
    return "\n".join(parts)


class Assistant:
    def __init__(self, provider: LLMProvider, library: LibraryService):
        self.provider, self.library = provider, library

    async def _ask(self, system: str, text: str, image: str | None) -> tuple[dict, LLMReply]:
        spent = LLMReply("", 0, 0, self.provider.model)               # tokens of every attempt count
        for attempt in (1, 2):
            try:
                reply = await self.provider.complete(system, text if attempt == 1 else text + RETRY_HINT, image)
                spent = LLMReply(reply.text, spent.tokens_in + reply.tokens_in, spent.tokens_out + reply.tokens_out, reply.model)
                return blocks.sanitize(blocks.extract_json(reply.text)), spent
            except LLMError as e:
                raise UpstreamError(str(e))
            except ValueError as e:                                    # includes JSON errors
                log.warning("ask.unparsable_reply %s", kv(provider=self.provider.name, attempt=attempt, error=e, reply_chars=len(reply.text)))
        raise UpstreamError("The AI reply could not be understood. Please try again.")

    async def answer(self, user_id: ObjectId, image: str | None, typed: str, use_library: bool,
                     memory: list[dict] | None = None, earlier: str = "", grey_ink: bool = False) -> Answer:
        started = time.perf_counter()
        turns = (memory or [])[-MEMORY_TURNS:]
        memory_text = _memory_text(turns)
        has_context = bool(memory_text or earlier or grey_ink)
        last_question = (turns[-1].get("read") or "") if turns else ""
        library = use_library and await asyncio.to_thread(self.library.has_active, user_id)
        excerpts = await asyncio.to_thread(self.library.search, user_id, typed, 4, last_question) if library and typed else []
        can_lookup = library and not excerpts and not typed
        out = Answer("", [])
        calls = 0

        if typed and not image and moderation.is_smalltalk(typed):     # "hi", "thanks"...: a fixed reply, no AI call
            out.read, out.flag = typed[:200], "off_topic"
            out.blocks = [{"t": "text", "text": moderation.OFF_TOPIC_MESSAGE}]
            return out

        def count(reply: LLMReply):
            out.tokens["in"] += reply.tokens_in
            out.tokens["out"] += reply.tokens_out

        result, reply = await self._ask(prompts.system_prompt(has_excerpts=bool(excerpts), can_lookup=can_lookup, animation=prompts.wants_animation(typed, bool(image)), has_context=has_context), _user_text(typed, excerpts, bool(image), memory_text, earlier), image)
        count(reply)
        calls += 1

        if result["lookup"] and can_lookup:                            # second pass: text only, with excerpts
            question = result["read"] or result["lookup"]
            excerpts = await asyncio.to_thread(self.library.search, user_id, f"{question} {result['lookup']}", 4, last_question)
            if excerpts:
                result, reply = await self._ask(prompts.system_prompt(has_excerpts=True, animation=prompts.wants_animation(question, False), has_context=bool(memory_text)), _user_text(question, excerpts, False, memory_text), None)
                count(reply)
                calls += 1

        if image and not typed and not result["blocks"] and not excerpts and not result["flag"]:   # the AI gave up on messy writing: one firmer retry
            result, reply = await self._ask(
                prompts.system_prompt(animation=False, has_context=has_context),
                (memory_text + chr(10) if memory_text else "") + "The picture shows handwriting that is a question or a math expression. Do not return an empty answer: "
                "write your best reading in \"read\" and answer it (if truly unreadable, say what you can make out and ask the student to write it larger).",
                image)
            count(reply)
            calls += 1

        if result["flag"] == "off_topic" and (typed or image):          # second opinion: never refuse a real study topic
            said = (result["read"] or typed).strip()
            unsure = bool(image) and not typed and (result["conf"] is None or result["conf"] < 0.8)
            if moderation.looks_educational(said) or unsure:
                again = (f'The student wrote: "{said}". ' if said else "") + (
                    "This is a study request (a topic, term, code request, formula or question from a school or college subject): answer it helpfully. "
                    "Do not use off_topic unless it is clearly about something else entirely.")
                result, reply = await self._ask(prompts.system_prompt(animation=False, has_context=has_context),
                                                (memory_text + chr(10) if memory_text else "") + again, None if said else image)
                count(reply)
                calls += 1

        out.read, out.blocks = result["read"], result["blocks"]
        out.flag, out.conf = result["flag"], result["conf"]
        if out.flag == "off_topic":                                    # one fixed, friendly message (the AI cannot be talked out of it)
            out.blocks = [{"t": "text", "text": moderation.OFF_TOPIC_MESSAGE}]
        elif out.flag == "abuse":
            out.blocks = []
        out.sources = sorted({f"{e['source']} p.{e['page']}" for e in excerpts})
        log.info("ask.done %s", kv(
            user=user_id, provider=self.provider.name, model=reply.model or self.provider.model, calls=calls,
            has_picture=bool(image), typed_chars=len(typed), tokens_in=out.tokens["in"], tokens_out=out.tokens["out"],
            blocks=",".join(b["t"] for b in out.blocks) or "none", flag=out.flag, conf=out.conf, sources=len(out.sources), ms=round((time.perf_counter() - started) * 1000),
        ))
        return out

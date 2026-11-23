"""Anthropic Messages API."""
from .base import LLMError, LLMProvider, LLMReply
from .http import post_json


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, *, max_tokens: int, timeout_s: int):
        self.api_key, self.model, self.max_tokens, self.timeout_s = api_key, model, max_tokens, timeout_s

    async def complete(self, system: str, text: str, image: str | None = None) -> LLMReply:
        if not self.api_key:
            raise LLMError("The anthropic API key is empty. Put it in the .env file.")
        content = []
        if image:
            header, b64 = image.split(",", 1)
            content.append({"type": "image", "source": {"type": "base64", "media_type": header[5:].split(";")[0], "data": b64}})
        content.append({"type": "text", "text": text})
        data = await post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": [{"role": "user", "content": content}]},
            self.timeout_s, self.name,
        )
        usage = data.get("usage") or {}
        reply = "".join(b.get("text", "") for b in data.get("content", []))
        return LLMReply(reply, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), data.get("model") or self.model)

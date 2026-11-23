"""OpenAI-style chat API. One class serves OpenAI itself, OpenRouter, and any local server that
copies the format (Ollama, LM Studio...): only the URL, key, model and a few options differ."""
from .base import LLMError, LLMProvider, LLMReply
from .http import post_json


class OpenAICompatible(LLMProvider):
    def __init__(self, name: str, base_url: str, api_key: str, model: str, *, max_tokens: int, timeout_s: int,
                 key_required: bool = True, official_openai: bool = False, extra_headers: dict | None = None):
        self.name, self.model = name, model
        self.base_url, self.api_key = base_url.rstrip("/"), api_key
        self.max_tokens, self.timeout_s = max_tokens, timeout_s
        self.key_required, self.official_openai = key_required, official_openai
        self.extra_headers = extra_headers or {}

    async def complete(self, system: str, text: str, image: str | None = None) -> LLMReply:
        if self.key_required and not self.api_key:
            raise LLMError(f"The {self.name} API key is empty. Put it in the .env file.")
        content = [{"type": "text", "text": text}]
        if image:
            content.append({"type": "image_url", "image_url": {"url": image}})
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        # OpenAI's newer models want max_completion_tokens; everything else uses max_tokens.
        body["max_completion_tokens" if self.official_openai else "max_tokens"] = self.max_tokens
        if self.official_openai:
            body["response_format"] = {"type": "json_object"}        # not every OpenRouter model supports this
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        data = await post_json(f"{self.base_url}/chat/completions", headers, body, self.timeout_s, self.name)
        try:
            reply = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"{self.name} returned an unexpected reply")
        usage = data.get("usage") or {}
        return LLMReply(reply, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), data.get("model") or self.model)

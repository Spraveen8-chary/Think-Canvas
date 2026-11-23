import asyncio

import httpx
import pytest

from backend.core.config import get_settings
from backend.services.llm import LLMError, http, openai_compat, registry


REAL_CLIENT = httpx.AsyncClient


def run(coro):
    return asyncio.run(coro)


def test_openrouter_uses_the_keys_and_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPEN_ROUTER_MODEL", "openai/gpt-4o")
    provider = registry.build_provider(get_settings())
    assert provider.name == "openrouter" and provider.model == "openai/gpt-4o"

    seen = {}

    async def fake_post(url, headers, body, timeout_s, name):
        seen.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": '{"read":"","blocks":[]}'}}], "usage": {"prompt_tokens": 120, "completion_tokens": 9}, "model": "openai/gpt-4o"}

    monkeypatch.setattr(openai_compat, "post_json", fake_post)
    reply = run(provider.complete("system", "hello", "data:image/png;base64,AAAA"))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-or-test" and seen["headers"]["X-Title"] == "Think Canvas"
    assert seen["body"]["model"] == "openai/gpt-4o" and seen["body"]["max_tokens"] == 700
    assert "response_format" not in seen["body"]                       # not every OpenRouter model accepts it
    assert seen["body"]["messages"][1]["content"][1]["type"] == "image_url"
    assert (reply.tokens_in, reply.tokens_out) == (120, 9)


def test_old_openrouter_variable_names_also_work(monkeypatch):
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "alt-name")
    assert get_settings().openrouter_api_key == "alt-name"


def test_missing_key_and_unknown_provider_give_clear_errors(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.delenv("OPEN_ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMError, match="API key is empty"):
        run(registry.get_provider().complete("s", "t"))
    monkeypatch.setenv("LLM_PROVIDER", "nonsense")
    with pytest.raises(LLMError, match="Unknown LLM_PROVIDER"):
        registry.get_provider()


def _mock_http(monkeypatch, statuses):
    calls = []

    def handler(request):
        calls.append(request)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return httpx.Response(status, json={"ok": True} if status == 200 else {"error": "x"})

    monkeypatch.setattr(http.httpx, "AsyncClient", lambda *a, **kw: REAL_CLIENT(*a, transport=httpx.MockTransport(handler), **kw))

    async def no_wait(_):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_wait)
    return calls


def test_temporary_failures_are_retried(monkeypatch):
    calls = _mock_http(monkeypatch, [503, 429, 200])
    assert run(http.post_json("http://x/y", {}, {}, 5, "test")) == {"ok": True}
    assert len(calls) == 3


def test_permanent_failures_are_not_retried(monkeypatch):
    calls = _mock_http(monkeypatch, [401])
    with pytest.raises(LLMError, match="rejected the API key"):
        run(http.post_json("http://x/y", {}, {}, 5, "test"))
    assert len(calls) == 1
    calls = _mock_http(monkeypatch, [503])
    with pytest.raises(LLMError, match="not responding"):
        run(http.post_json("http://x/y", {}, {}, 5, "test"))
    assert len(calls) == 3                                              # first try + two retries

"""Chooses the provider named by LLM_PROVIDER in .env."""
from ...core.config import Settings, get_settings
from .anthropic import AnthropicProvider
from .base import LLMError, LLMProvider
from .cli import CliProvider
from .openai_compat import OpenAICompatible

PROVIDERS = ("openrouter", "openai", "anthropic", "claude-cli", "codex-cli")


def build_provider(s: Settings) -> LLMProvider:
    common = dict(max_tokens=s.max_output_tokens, timeout_s=s.llm_timeout_s)
    if s.provider == "openrouter":
        return OpenAICompatible(
            "openrouter", "https://openrouter.ai/api/v1", s.openrouter_api_key, s.openrouter_model,
            extra_headers={"HTTP-Referer": "http://localhost", "X-Title": "Think Canvas"}, **common,
        )
    if s.provider == "openai":
        official = "api.openai.com" in s.openai_base_url          # a custom URL means a local model: no key needed
        return OpenAICompatible("openai", s.openai_base_url, s.openai_api_key, s.openai_model,
                                key_required=official, official_openai=official, **common)
    if s.provider == "anthropic":
        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model, **common)
    if s.provider == "claude-cli":
        return CliProvider("claude-cli", s.claude_cmd, s.llm_timeout_s)
    if s.provider == "codex-cli":
        return CliProvider("codex-cli", s.codex_cmd, s.llm_timeout_s)
    raise LLMError(f'Unknown LLM_PROVIDER "{s.provider}". Use one of: {", ".join(PROVIDERS)}.')


def get_provider() -> LLMProvider:
    return build_provider(get_settings())

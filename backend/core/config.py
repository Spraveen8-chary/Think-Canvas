"""Settings. One immutable object, read from the project's .env file (real environment variables win).

Every other module asks for `get_settings()`; nothing else reads os.environ. Secrets live here
only as plain fields and are never logged (see core/logging.py).
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
load_dotenv(ROOT / ".env")


def _str(name: str, default: str = "", *aliases: str) -> str:
    for n in (name, *aliases):
        if os.environ.get(n):
            return os.environ[n].strip()
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # server
    port: int
    log_level: str
    log_dir: Path
    # database
    mongo_uri: str
    mongo_db: str
    # AI
    provider: str
    max_output_tokens: int
    llm_timeout_s: int
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    openrouter_api_key: str
    openrouter_model: str
    anthropic_api_key: str
    anthropic_model: str
    claude_cmd: str
    codex_cmd: str
    # product behaviour
    auto_ask_delay_ms: int
    ask_rate_per_min: int          # AI calls per user per minute (protects your API budget)
    auth_rate_per_min: int         # login/register attempts per client per minute
    # voice: AssemblyAI STT & Gemini Live
    assemblyai_api_key: str
    gemini_api_key: str
    gemini_live_model: str
    embedding_model: str
    stt_autosubmit_silence_ms: int


def get_settings() -> Settings:
    return Settings(
        port=_int("PORT", 3888),
        log_level=_str("LOG_LEVEL", "INFO").upper(),
        log_dir=Path(_str("LOG_DIR", str(ROOT / "logs"))),
        mongo_uri=_str("MONGODB_URI", "mongodb://localhost:27017"),
        mongo_db=_str("MONGODB_DB", "think_canvas"),
        provider=_str("LLM_PROVIDER", "openai").lower(),
        max_output_tokens=_int("MAX_OUTPUT_TOKENS", 2500),
        llm_timeout_s=_int("LLM_TIMEOUT_S", 90),
        openai_api_key=_str("OPENAI_API_KEY"),
        openai_model=_str("OPENAI_MODEL", "gpt-4o"),
        openai_base_url=_str("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openrouter_api_key=_str("OPEN_ROUTER_API_KEY", "", "OPENROUTER_API_KEY"),
        openrouter_model=_str("OPEN_ROUTER_MODEL", "openai/gpt-4o", "OPENROUTER_MODEL"),
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        anthropic_model=_str("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        claude_cmd=_str("CLAUDE_CMD", "claude"),
        codex_cmd=_str("CODEX_CMD", "codex"),
        auto_ask_delay_ms=_int("AUTO_ASK_DELAY_MS", 2500),
        ask_rate_per_min=_int("ASK_RATE_PER_MIN", 20),
        auth_rate_per_min=_int("AUTH_RATE_PER_MIN", 10),
        assemblyai_api_key=_str("ASSEMBLYAI_API_KEY"),
        gemini_api_key=_str("GEMINI_API_KEY"),
        gemini_live_model=_str("GEMINI_LIVE_MODEL", "models/gemini-3.8-live"),
        embedding_model=_str("EMBEDDING_MODEL", "text-embedding-3-small"),
        stt_autosubmit_silence_ms=_int("STT_AUTOSUBMIT_SILENCE_MS", 5000),
    )

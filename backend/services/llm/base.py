"""The AI provider contract. The rest of the app depends on this, never on a specific vendor
(Strategy pattern): adding a provider means one new class and one line in registry.py."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMError(Exception):
    """The AI provider failed. The message is safe to show to the user."""


@dataclass(frozen=True)
class LLMReply:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class LLMProvider(ABC):
    name: str = "provider"
    model: str = ""

    @abstractmethod
    async def complete(self, system: str, text: str, image: str | None = None) -> LLMReply:
        """One request: system prompt + user text (+ optional PNG/JPEG data URL). Returns the reply text and token usage."""

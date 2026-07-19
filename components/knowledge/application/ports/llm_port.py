"""Port for LLM interactions — domain stays provider-free.

Any LLM backend (OpenAI, Azure, Gemini, Ollama, …) implements this
contract so the application layer never couples to a specific SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LlmResponse:
    """Normalised LLM output returned by every adapter."""

    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    raw: Any = None  # original provider response for callers that need it


class LlmPort(ABC):
    """Abstract contract every LLM adapter must satisfy."""

    @abstractmethod
    def invoke(self, prompt: str, **kwargs) -> LlmResponse:
        """Synchronous single-turn completion."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> LlmResponse:
        """Multi-turn chat with role-based messages.

        Args:
            messages: List of {"role": "system"|"user"|"assistant", "content": "..."}
        """
        ...

    @abstractmethod
    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Yield token-by-token for streaming endpoints."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable slug identifying this backend (e.g. 'openai')."""
        ...

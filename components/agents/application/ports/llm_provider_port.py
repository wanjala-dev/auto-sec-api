"""Port for LLM instantiation — keeps adapters free of persistence imports.

The LangChain adapter currently imports ``LLMFactory`` directly from the
persistence layer.  This port abstracts that dependency so we can swap
the underlying LLM provider (OpenAI, Anthropic, local models, …) without
touching any adapter code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProviderPort(ABC):
    """Create / resolve LLM instances by provider slug or model name."""

    @abstractmethod
    def get_llm(
        self,
        provider_slug: str = "openai",
        *,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        streaming: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Return a framework-agnostic LLM handle.

        The returned object must be usable by the active runtime adapter
        (e.g. a LangChain ``BaseLLM`` when using the LangChain adapter).
        """
        ...

    @abstractmethod
    def get_default_llm(
        self,
        *,
        model_name: str | None = None,
        temperature: float = 0.7,
        streaming: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Convenience shortcut — resolve the workspace-default provider."""
        ...

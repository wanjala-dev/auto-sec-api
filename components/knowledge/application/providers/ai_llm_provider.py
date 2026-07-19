"""Dynamic LLM provider registry.

Resolves a provider slug to the corresponding ``LlmPort`` adapter at
runtime.  New backends are added by registering them in ``_ADAPTERS``.

Usage::

    provider = AILlmProvider()
    llm = provider.get_port("openai")          # → OpenAILlmAdapter
    llm = provider.get_port("azure")           # → AzureLlmAdapter
    llm = provider.get_port("anthropic",
                            model_name="claude-sonnet-4-20250514")  # → AnthropicLlmAdapter
    llm = provider.get_port("openai",
                            model_name="gpt-4",
                            temperature=0.2)    # → configured adapter
"""

from __future__ import annotations

import os

from components.knowledge.domain.errors import UnsupportedProviderError
from components.knowledge.application.ports.llm_port import LlmPort


class AILlmProvider:
    """Registry that lazily constructs the right LLM adapter."""

    # slug → callable(**kwargs) → LlmPort
    _FACTORIES: dict[str, type] = {}

    def __init__(self) -> None:
        # Register known adapters — lazy import so modules stay optional
        if not AILlmProvider._FACTORIES:
            from components.knowledge.infrastructure.adapters.llm.anthropic_llm_adapter import AnthropicLlmAdapter
            from components.knowledge.infrastructure.adapters.llm.azure_llm_adapter import AzureLlmAdapter
            from components.knowledge.infrastructure.adapters.llm.openai_llm_adapter import OpenAILlmAdapter

            AILlmProvider._FACTORIES = {
                "openai": OpenAILlmAdapter,
                "azure": AzureLlmAdapter,
                "anthropic": AnthropicLlmAdapter,
            }

    def get_port(self, provider: str, **kwargs) -> LlmPort:
        """Return an ``LlmPort`` for *provider*, or raise ``UnsupportedProviderError``."""
        factory = self._FACTORIES.get(provider)
        if factory is None:
            raise UnsupportedProviderError("LLM", provider, list(self._FACTORIES))
        return factory(**kwargs)

    def get_default_port(self, **kwargs) -> LlmPort:
        """Auto-detect: Azure if env vars present, else OpenAI."""
        has_azure = bool(
            os.environ.get("AZURE_OPENAI_API_KEY")
            and os.environ.get("AZURE_OPENAI_API_BASE")
        )
        slug = "azure" if has_azure else "openai"
        return self.get_port(slug, **kwargs)

    @classmethod
    def register(cls, slug: str, factory: type) -> None:
        """Register a new LLM adapter at runtime (e.g. Gemini, Ollama)."""
        cls._FACTORIES[slug] = factory

    def available_providers(self) -> list[str]:
        return sorted(self._FACTORIES)

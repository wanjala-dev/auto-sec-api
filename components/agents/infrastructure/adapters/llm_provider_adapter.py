"""Adapter implementing LLMProviderPort via the persistence LLMFactory."""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.llm_provider_port import LLMProviderPort


class LLMFactoryAdapter(LLMProviderPort):
    """Delegates to ``infrastructure.persistence.ai.llms.factory.LLMFactory``."""

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
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        return LLMFactory.create_llm(
            provider=provider_slug,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
            **kwargs,
        )

    def get_default_llm(
        self,
        *,
        model_name: str | None = None,
        temperature: float = 0.7,
        streaming: bool = False,
        **kwargs: Any,
    ) -> Any:
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        return LLMFactory.create_llm(
            model_name=model_name,
            temperature=temperature,
            streaming=streaming,
            **kwargs,
        )

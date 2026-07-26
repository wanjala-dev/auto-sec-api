"""Published seam for knowledge's LangChain LLM factory.

The knowledge context owns LLM construction. Other contexts that need a raw
LangChain chat model (the agents context's ReAct / deep-planner infrastructure)
reach it through this application-layer provider instead of importing
``knowledge.infrastructure.factories.llms.factory`` directly — cross-context
infrastructure imports are forbidden (ADR 0004 infra-boundary series).

Unlike :class:`AILlmProvider` (which returns knowledge's ``LlmPort`` chat
abstraction), this provider returns the raw LangChain model, because its
consumers are themselves LangChain infrastructure that needs the concrete
``BaseChatModel``. The provider is the composition seam that publishes that
infrastructure object across the context boundary.
"""

from __future__ import annotations

from typing import Any


class LangchainLlmFactoryProvider:
    """Driving-side facade over knowledge's ``LLMFactory`` (LangChain models)."""

    def create_llm(self, *args: Any, **kwargs: Any) -> Any:
        """Construct a LangChain model for an explicit provider (passthrough to ``LLMFactory.create_llm``)."""
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        return LLMFactory.create_llm(*args, **kwargs)

    def get_llm(self, *args: Any, **kwargs: Any) -> Any:
        """Construct the default/resolved LangChain model (passthrough to ``LLMFactory.get_llm``)."""
        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        return LLMFactory.get_llm(*args, **kwargs)


_default = LangchainLlmFactoryProvider()


def get_langchain_llm_factory_provider() -> LangchainLlmFactoryProvider:
    """Return the default provider — the published seam for knowledge's LangChain LLM factory."""
    return _default

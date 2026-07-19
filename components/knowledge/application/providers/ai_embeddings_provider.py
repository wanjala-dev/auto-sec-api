"""Dynamic embeddings provider registry.

Resolves a provider slug to the corresponding ``EmbeddingsPort`` adapter
at runtime.

Usage::

    provider = AIEmbeddingsProvider()
    emb = provider.get_port("openai")
    emb = provider.get_port("huggingface")
"""

from __future__ import annotations

from components.knowledge.domain.errors import UnsupportedProviderError
from components.knowledge.application.ports.embeddings_port import EmbeddingsPort


class AIEmbeddingsProvider:
    """Registry that lazily constructs the right embeddings adapter."""

    _FACTORIES: dict[str, type] = {}

    def __init__(self) -> None:
        if not AIEmbeddingsProvider._FACTORIES:
            from components.knowledge.infrastructure.adapters.embeddings.azure_embeddings_adapter import (
                AzureEmbeddingsAdapter,
            )
            from components.knowledge.infrastructure.adapters.embeddings.openai_embeddings_adapter import (
                OpenAIEmbeddingsAdapter,
            )

            AIEmbeddingsProvider._FACTORIES = {
                "openai": OpenAIEmbeddingsAdapter,
                "azure": AzureEmbeddingsAdapter,
            }


    def get_port(self, provider: str, **kwargs) -> EmbeddingsPort:
        factory = self._FACTORIES.get(provider)
        if factory is None:
            raise UnsupportedProviderError("embeddings", provider, list(self._FACTORIES))
        return factory(**kwargs)

    @classmethod
    def register(cls, slug: str, factory: type) -> None:
        cls._FACTORIES[slug] = factory

    def available_providers(self) -> list[str]:
        return sorted(self._FACTORIES)

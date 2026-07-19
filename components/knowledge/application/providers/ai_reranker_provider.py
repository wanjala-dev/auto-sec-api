"""Dynamic reranker provider registry.

Resolves a provider slug to the corresponding ``RerankerPort`` adapter
at runtime.

Usage::

    provider = AIRerankerProvider()
    reranker = provider.get_port("cross-encoder")
    reranker = provider.get_port()  # default
"""

from __future__ import annotations

import logging
import os

from components.knowledge.domain.errors import UnsupportedProviderError
from components.knowledge.application.ports.reranker_port import RerankerPort

logger = logging.getLogger(__name__)

_DEFAULT_RERANKER_SLUG = os.environ.get("RERANKER_PROVIDER", "cross-encoder")


class AIRerankerProvider:
    """Registry that lazily constructs the right reranker adapter."""

    _FACTORIES: dict[str, type] = {}

    def __init__(self) -> None:
        if not AIRerankerProvider._FACTORIES:
            self._register_builtin_factories()

    @classmethod
    def _register_builtin_factories(cls) -> None:
        try:
            from components.knowledge.infrastructure.adapters.reranker.cross_encoder_reranker_adapter import (
                CrossEncoderRerankerAdapter,
            )

            cls._FACTORIES["cross-encoder"] = CrossEncoderRerankerAdapter
        except ImportError:
            logger.debug("cross-encoder reranker unavailable")

    def get_port(self, provider: str | None = None, **kwargs) -> RerankerPort:
        slug = provider or _DEFAULT_RERANKER_SLUG
        factory = self._FACTORIES.get(slug)
        if factory is None:
            raise UnsupportedProviderError("reranker", slug, list(self._FACTORIES))
        return factory(**kwargs)

    @classmethod
    def register(cls, slug: str, factory: type) -> None:
        cls._FACTORIES[slug] = factory

    def available_providers(self) -> list[str]:
        return sorted(self._FACTORIES)

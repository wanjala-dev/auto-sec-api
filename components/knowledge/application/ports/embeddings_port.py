"""Port for text-embedding providers — domain stays SDK-free.

Adapters wrap OpenAI, Azure, HuggingFace, Elasticsearch-native, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingsPort(ABC):
    """Abstract contract every embeddings adapter must satisfy."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a single text string."""
        ...

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch-embed multiple texts. Default loops over ``embed_text``."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return a stable slug identifying this backend (e.g. 'openai')."""
        ...

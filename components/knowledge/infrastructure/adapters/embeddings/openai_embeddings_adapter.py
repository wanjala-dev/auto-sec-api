"""OpenAI embeddings adapter — wraps apps.ai.embeddings.openai behind EmbeddingsPort."""

from __future__ import annotations

from components.knowledge.application.ports.embeddings_port import EmbeddingsPort


class OpenAIEmbeddingsAdapter(EmbeddingsPort):

    def __init__(self, *, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory
            self._instance = EmbeddingsFactory.create_embeddings(provider="openai")
        return self._instance

    def embed_text(self, text: str) -> list[float]:
        instance = self._get_instance()
        return instance.embed_query(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        instance = self._get_instance()
        return instance.embed_documents(texts)

    def provider_name(self) -> str:
        return "openai"

"""Application service for the Knowledge bounded context.

Owns embeddings, vector stores, LLM provider management, and document lifecycle.
Delegates to infrastructure for provider management.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from components.shared_kernel.domain.errors import ValidationError


@dataclass
class KnowledgeService:
    """Application service for knowledge/RAG infrastructure.

    Provides provider management, document operations, and infrastructure
    port access for embeddings, vector stores, and LLMs.
    """

    def get_llm_port(self, provider: str = None, **kwargs) -> Any:
        """Get an LLM port without tight coupling to infrastructure."""
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider
        llm_provider = AILlmProvider()
        if provider:
            return llm_provider.get_port(provider, **kwargs)
        return llm_provider.get_default_port(**kwargs)

    def get_embeddings_port(self, provider: str = None, **kwargs) -> Any:
        """Get an embeddings port without tight coupling to infrastructure."""
        from components.knowledge.application.providers.ai_embeddings_provider import AIEmbeddingsProvider
        embeddings_provider = AIEmbeddingsProvider()
        if provider:
            return embeddings_provider.get_port(provider, **kwargs)
        return embeddings_provider.get_default_port(**kwargs)

    def get_vector_store_port(self, provider: str = None, **kwargs) -> Any:
        """Get a vector store port without tight coupling to infrastructure."""
        from components.knowledge.application.providers.ai_vector_store_provider import AIVectorStoreProvider
        vector_store_provider = AIVectorStoreProvider()
        if provider:
            return vector_store_provider.get_port(provider, **kwargs)
        return vector_store_provider.get_default_port(**kwargs)

    def list_llm_providers(self) -> list[str]:
        """List available LLM providers."""
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider
        return AILlmProvider().get_available_providers()

    def list_embeddings_providers(self) -> list[str]:
        """List available embeddings providers."""
        from components.knowledge.application.providers.ai_embeddings_provider import AIEmbeddingsProvider
        return AIEmbeddingsProvider().get_available_providers()

    def list_vector_store_providers(self) -> list[str]:
        """List available vector store providers."""
        from components.knowledge.application.providers.ai_vector_store_provider import AIVectorStoreProvider
        return AIVectorStoreProvider().get_available_providers()

    def get_llm_provider_info(self, provider: str) -> dict:
        """Get metadata about a specific LLM provider."""
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider
        return AILlmProvider().get_provider_info(provider)

    def get_embeddings_provider_info(self, provider: str) -> dict:
        """Get metadata about a specific embeddings provider."""
        from components.knowledge.application.providers.ai_embeddings_provider import AIEmbeddingsProvider
        return AIEmbeddingsProvider().get_provider_info(provider)

    def get_vector_store_provider_info(self, provider: str) -> dict:
        """Get metadata about a specific vector store provider."""
        from components.knowledge.application.providers.ai_vector_store_provider import AIVectorStoreProvider
        return AIVectorStoreProvider().get_provider_info(provider)

    def get_document_by_id(self, doc_id: str):
        """Query a document by ID (delegates to infrastructure)."""
        from components.knowledge.infrastructure.repositories.document_repository import (
            OrmDocumentRepository,
        )
        return OrmDocumentRepository().get_by_id(doc_id)

    def create_document(self, *, workspace_id, **kwargs):
        """Create a new document (delegates to infrastructure).

        ``workspace_id`` is required as a keyword argument — the upload
        endpoint enforces this at the API boundary and the model
        signature documents it here so service callers don't
        accidentally drop tenant scope.  Pre-Tier-2 the FK was
        nullable; new callers always pass a non-empty workspace_id.
        See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #4.
        """
        if not workspace_id:
            raise ValidationError(
                "create_document requires a non-empty workspace_id — "
                "tenant scope cannot be silently dropped."
            )
        from components.knowledge.infrastructure.repositories.document_repository import (
            OrmDocumentRepository,
        )
        return OrmDocumentRepository().create(
            workspace_id=str(workspace_id),
            **kwargs,
        )

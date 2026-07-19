"""Elasticsearch vector-store adapter — wraps apps.ai.vector_stores.elasticsearch behind VectorStorePort."""

from __future__ import annotations

from components.knowledge.application.ports.vector_store_port import RetrievedChunk, VectorStorePort


class ElasticsearchVectorStoreAdapter(VectorStorePort):

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        from components.agents.infrastructure.adapters.langchain.chains.retrieval import normalize_metadata_value as _s
        from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory
        from components.knowledge.infrastructure.factories.vector_stores.factory import VectorStoreFactory

        pdf_id = (filters or {}).get("pdf_id")
        workspace_id = (filters or {}).get("workspace_id")
        user_id = (filters or {}).get("user_id")

        retriever = VectorStoreFactory.create_retriever(
            provider="elasticsearch",
            chat_args=type("ChatArgs", (), {
                "pdf_id": pdf_id,
                "workspace_id": workspace_id,
                "user_id": user_id,
            })(),
            k=k,
            embeddings_instance=EmbeddingsFactory.create_embeddings(provider="openai"),
        )

        docs = retriever.get_relevant_documents(query)

        # Apply metadata filters the same way the controllers do
        filtered = docs
        if pdf_id:
            filtered = [d for d in filtered if d.metadata.get("pdf_id") == _s(pdf_id)]
        if workspace_id:
            filtered = [d for d in filtered if d.metadata.get("workspace_id") == _s(workspace_id)]
        if user_id:
            filtered = [d for d in filtered if d.metadata.get("user_id") == _s(user_id)]

        return [
            RetrievedChunk(
                content=doc.page_content,
                metadata=doc.metadata,
                score=getattr(doc, "score", 0.0),
            )
            for doc in filtered
        ]

    def has_indexed_content(
        self,
        *,
        pdf_id: str | None = None,
        workspace_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        from components.agents.infrastructure.adapters.langchain.chains.retrieval import has_indexed_chunks as _has_indexed_chunks
        from components.knowledge.infrastructure.factories.embeddings.factory import EmbeddingsFactory
        from components.knowledge.infrastructure.factories.vector_stores.factory import VectorStoreFactory

        retriever = VectorStoreFactory.create_retriever(
            provider="elasticsearch",
            chat_args=type("ChatArgs", (), {
                "pdf_id": pdf_id,
                "workspace_id": workspace_id,
                "user_id": user_id,
            })(),
            k=1,
            embeddings_instance=EmbeddingsFactory.create_embeddings(provider="openai"),
        )
        return _has_indexed_chunks(retriever, pdf_id, workspace_id, user_id)

    def provider_name(self) -> str:
        return "elasticsearch"

"""Shared document processor — RAG-based extraction for any document type.

Lives in the shared platform layer. Orchestrates:
  1. Save file to temp location
  2. Index via knowledge layer (chunks → embeddings → Elasticsearch)
  3. Retrieve relevant chunks via hybrid search
  4. Extract structured data via LLM
  5. Return parsed rows for the calling context to apply

Supports: PDF, DOCX, TXT, CSV. Adding a new format means adding
a loader in the knowledge layer — this processor doesn't change.

Usage from any bounded context:
    from components.shared_platform.infrastructure.services.document_processor import (
        DocumentProcessor,
    )
    processor = DocumentProcessor()
    result = processor.process(
        file_content=raw_bytes,
        file_type="pdf",
        extraction_prompt="Extract all budget line items...",
        workspace_id="...",
        user_id="...",
    )
    # result.rows = [{"item": "Beans", "amount": 640000, ...}, ...]
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

FILE_EXTENSIONS = {
    "pdf": ".pdf",
    "docx": ".docx",
    "doc": ".docx",
    "txt": ".txt",
    "csv": ".csv",
}


@dataclass(frozen=True)
class DocumentProcessingResult:
    """Result of processing a document through RAG."""
    success: bool
    doc_id: str
    chunks_indexed: int = 0
    chunks_retrieved: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)
    raw_context: str = ""
    raw_llm_response: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DocumentProcessor:
    """RAG-based document processor — reusable across bounded contexts."""

    def process(
        self,
        file_content: bytes,
        *,
        file_type: str = "pdf",
        extraction_prompt: str,
        workspace_id: str,
        user_id: str,
        search_query: str = "transactions expenses items amounts",
        max_chunks: int = 15,
        llm_provider: str | None = None,
        llm_model: str = "gpt-3.5-turbo",
        llm_max_tokens: int = 3000,
    ) -> DocumentProcessingResult:
        """Process a document through the full RAG pipeline.

        Args:
            file_content: Raw file bytes
            file_type: "pdf", "docx", "txt", "csv"
            extraction_prompt: Prompt for the LLM (must contain {context} placeholder)
            workspace_id: Workspace ID for metadata tagging
            user_id: User ID for metadata tagging
            search_query: What to search for in the indexed document
            max_chunks: How many chunks to retrieve
            llm_provider: Override LLM provider
            llm_model: Model to use
            llm_max_tokens: Max tokens for LLM response

        Returns:
            DocumentProcessingResult with extracted rows
        """
        doc_id = str(uuid.uuid4())
        ext = FILE_EXTENSIONS.get(file_type.lower(), ".pdf")

        # ── Step 1: Index the document ───────────────────────────────
        index_result = self._index_document(
            file_content, doc_id, ext, workspace_id, user_id
        )
        if not index_result["success"]:
            return DocumentProcessingResult(
                success=False,
                doc_id=doc_id,
                errors=index_result.get("errors", ["Indexing failed"]),
            )

        chunks_indexed = index_result.get("chunks", 0)

        # ── Step 2: Retrieve relevant chunks ─────────────────────────
        context, chunks_retrieved, retrieve_warnings = self._retrieve_chunks(
            doc_id, workspace_id, search_query, max_chunks
        )
        if not context:
            return DocumentProcessingResult(
                success=False,
                doc_id=doc_id,
                chunks_indexed=chunks_indexed,
                errors=["No relevant content found after indexing."],
                warnings=retrieve_warnings,
            )

        # ── Step 3: Extract structured data via LLM ──────────────────
        rows, raw_response, extract_errors = self._extract_with_llm(
            context, extraction_prompt, llm_provider, llm_model, llm_max_tokens
        )

        return DocumentProcessingResult(
            success=len(extract_errors) == 0,
            doc_id=doc_id,
            chunks_indexed=chunks_indexed,
            chunks_retrieved=chunks_retrieved,
            rows=rows or [],
            raw_context=context,
            raw_llm_response=raw_response,
            errors=extract_errors,
            warnings=retrieve_warnings + [f"Indexed {chunks_indexed} chunks, retrieved {chunks_retrieved}."],
        )

    # ── Private methods ──────────────────────────────────────────────

    def _index_document(
        self,
        file_content: bytes,
        doc_id: str,
        ext: str,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Write to temp file and index via knowledge layer."""
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(file_content)
        tmp.close()

        try:
            if ext in (".pdf",):
                from components.knowledge.infrastructure.adapters.pdf_embeddings import (
                    create_embeddings_for_pdf,
                )
                result = create_embeddings_for_pdf(
                    pdf_id=doc_id,
                    pdf_path=tmp.name,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                return {
                    "success": result.get("success", False),
                    "chunks": result.get("chunks_created", 0),
                    "errors": [result.get("error")] if not result.get("success") else [],
                }
            elif ext in (".docx", ".doc"):
                from components.knowledge.infrastructure.adapters.document_embeddings import (
                    create_embeddings_for_document,
                )
                result = create_embeddings_for_document(
                    file_id=doc_id,
                    file_path=tmp.name,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                return {
                    "success": result.get("success", False),
                    "chunks": result.get("chunks_created", 0),
                    "errors": [result.get("error")] if not result.get("success") else [],
                }
            else:
                # For txt/csv, create simple chunks
                content = file_content.decode("utf-8-sig", errors="replace")
                from langchain.text_splitter import RecursiveCharacterTextSplitter
                from langchain.schema import Document

                splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
                chunks = splitter.split_text(content)
                docs = [
                    Document(
                        page_content=chunk,
                        metadata={
                            "pdf_id": doc_id,
                            "user_id": user_id,
                            "workspace_id": workspace_id,
                            "type": ext.replace(".", ""),
                        },
                    )
                    for chunk in chunks
                ]

                from components.knowledge.infrastructure.factories.embeddings.factory import (
                    EmbeddingsFactory,
                )
                from components.knowledge.infrastructure.factories.vector_stores.factory import (
                    VectorStoreFactory,
                )
                # No provider= kwarg: factory reads settings.VECTOR_STORE_PROVIDER.
                vs = VectorStoreFactory.create_vector_store(
                    embeddings_instance=EmbeddingsFactory.create_embeddings(provider="openai"),
                )
                vs.add_documents(docs)
                return {"success": True, "chunks": len(docs)}
        except Exception as exc:
            logger.error("Document indexing failed: %s", exc)
            return {"success": False, "errors": [str(exc)[:200]]}
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def _retrieve_chunks(
        self,
        doc_id: str,
        workspace_id: str,
        search_query: str,
        max_chunks: int,
    ) -> tuple[str, int, list[str]]:
        """Retrieve ALL chunks for this document from the vector store.

        Provider-agnostic: the active backend is read from
        ``settings.VECTOR_STORE_PROVIDER``. When that's elasticsearch we
        use the fast direct ES term query (no embedding needed); when
        it's pgvector (or anything else) we use the langchain
        similarity_search with a provider-native filter dict.

        For user-uploaded documents destined for extraction (not
        knowledge-base search) we want EVERY chunk belonging to this
        doc_id so the LLM sees the complete content, so we pass a
        large k.
        """
        from django.conf import settings as _settings

        warnings: list[str] = []
        provider = getattr(_settings, "VECTOR_STORE_PROVIDER", "pgvector")

        # ── Fast path: direct ES query when ES is the active backend ─
        if provider == "elasticsearch":
            try:
                from components.knowledge.infrastructure.factories.vector_stores.elasticsearch import (
                    create_elasticsearch_client,
                )
                import os as _os

                es = create_elasticsearch_client()
                index_name = _os.environ.get(
                    "ELASTICSEARCH_INDEX_NAME", "ai_documents"
                )
                body = {
                    "size": max(max_chunks, 200),
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"metadata.pdf_id": str(doc_id)}},
                                {"term": {"metadata.workspace_id": str(workspace_id)}},
                            ]
                        }
                    },
                }
                res = es.search(index=index_name, body=body)
                hits = res.get("hits", {}).get("hits", [])
                if hits:
                    chunks = [
                        (
                            hit.get("_source", {}).get("text")
                            or hit.get("_source", {}).get("content")
                            or hit.get("_source", {}).get("page_content")
                            or ""
                        )
                        for hit in hits
                    ]
                    chunks = [c for c in chunks if c.strip()]
                    if chunks:
                        return "\n\n".join(chunks), len(chunks), warnings
                warnings.append(
                    "Direct ES query returned no chunks; falling back to similarity search."
                )
            except Exception as exc:
                logger.warning(
                    "Direct ES chunk retrieval failed, falling back: %s", exc
                )

        # ── Similarity search via the configured backend ─────────────
        try:
            from components.knowledge.infrastructure.factories.embeddings.factory import (
                EmbeddingsFactory,
            )
            from components.knowledge.infrastructure.factories.vector_stores.factory import (
                VectorStoreFactory,
            )

            vs = VectorStoreFactory.create_vector_store(
                embeddings_instance=EmbeddingsFactory.create_embeddings(provider="openai"),
            )

            # Filter format differs per backend:
            # - ES expects {"bool": {"must": [{"term": {...}}, ...]}}
            # - pgvector / Postgres accepts a flat dict {key: value}
            #   matched against the JSONB metadata column.
            if provider == "elasticsearch":
                vs_filter: dict = {
                    "bool": {
                        "must": [
                            {"term": {"metadata.pdf_id": str(doc_id)}},
                            {"term": {"metadata.workspace_id": str(workspace_id)}},
                        ]
                    }
                }
            else:
                vs_filter = {
                    "pdf_id": str(doc_id),
                    "workspace_id": str(workspace_id),
                }

            docs = vs.similarity_search(
                query=search_query,
                k=max_chunks,
                filter=vs_filter,
            )
            if not docs:
                return "", 0, ["No chunks matched the search query."]

            context = "\n\n".join(d.page_content for d in docs if d.page_content)
            return context, len(docs), warnings
        except Exception as exc:
            logger.error("Vector search failed for doc %s: %s", doc_id, exc)
            return "", 0, [f"Vector search failed: {str(exc)[:200]}"]

    @staticmethod
    def _extract_with_llm(
        context: str,
        prompt_template: str,
        provider: str | None,
        model: str,
        max_tokens: int,
    ) -> tuple[list[dict] | None, str, list[str]]:
        """Send context to LLM with the extraction prompt."""
        try:
            from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

            resolved = provider or ("openai" if os.environ.get("OPENAI_API_KEY") else "azure")
            llm = LLMFactory.create_llm(
                provider=resolved, model_name=model,
                temperature=0.1, max_tokens=max_tokens,
            )

            # Limit context to ~15k chars — keeps total prompt under
            # the sweet spot for gpt-4o-mini and avoids OpenAI timeouts.
            truncated = context[:15000]
            prompt = prompt_template.format(context=truncated)
            logger.info(
                "LLM extraction: model=%s, prompt_len=%d, max_tokens=%d",
                model, len(prompt), max_tokens,
            )
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            logger.info("LLM response: %d chars", len(content))

            # Strip markdown code fences (```json ... ```)
            cleaned = content.strip()
            if cleaned.startswith("```"):
                first_newline = cleaned.find("\n")
                if first_newline > 0:
                    cleaned = cleaned[first_newline + 1:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()

            start = cleaned.find("[")
            if start < 0:
                logger.warning("LLM did not return JSON array: %s", cleaned[:300])
                return None, content, [f"LLM did not return JSON array: {cleaned[:200]}"]

            json_str = cleaned[start:]
            end = json_str.rfind("]")

            if end < 0:
                # Response was truncated (hit max_tokens) — find the
                # last complete object and close the array.
                last_brace = json_str.rfind("}")
                if last_brace > 0:
                    json_str = json_str[: last_brace + 1] + "]"
                    logger.info("Repaired truncated JSON array (closed at char %d)", last_brace)
                else:
                    return None, content, ["LLM response was truncated and could not be repaired."]
            else:
                json_str = json_str[: end + 1]

            rows = json.loads(json_str)
            logger.info("LLM extracted %d rows", len(rows))
            return rows, content, []
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error: %s", str(exc)[:200])
            return None, "", [f"Failed to parse LLM response as JSON: {str(exc)[:200]}"]
        except Exception as exc:
            logger.error("LLM extraction failed: %s: %s", type(exc).__name__, str(exc)[:300])
            return None, "", [f"LLM extraction failed: {str(exc)[:200]}"]

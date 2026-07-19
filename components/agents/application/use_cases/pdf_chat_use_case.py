"""Use case: answer a user question (or summarize) against a PDF document.

Orchestrates:
    1. Check indexed content exists via VectorStorePort
    2. Retrieve relevant chunks via hybrid search (BM25 + vector)
    3. Rerank chunks with cross-encoder for higher precision
    4. Detect intent via domain value object (tldr / summary / qa)
    5. Build prompt (delegates to pure prompt builders)
    6. Invoke LLM via LlmPort
    7. Return structured result

Framework-free — no Django, DRF, or ORM imports.
"""

from __future__ import annotations

import logging
from typing import Any

from components.agents.application.commands.pdf_chat_command import (
    PdfChatCommand,
    PdfChatFailure,
    PdfChatNoContent,
    PdfChatNoRelevantDocs,
    PdfChatSuccess,
)
from components.agents.domain.value_objects.pdf_intent import (
    PdfIntent,
    detect_pdf_intent,
    extract_search_words,
)
from components.agents.domain.value_objects.pdf_prompts import (
    build_pdf_qa_prompt,
    build_pdf_summary_prompt,
    build_pdf_tldr_prompt,
)
from components.knowledge.application.ports.llm_port import LlmPort
from components.knowledge.application.ports.reranker_port import RerankerPort
from components.knowledge.application.ports.vector_store_port import RetrievedChunk, SearchMode, VectorStorePort
from components.shared_kernel.application.handlers import CommandHandler

logger = logging.getLogger(__name__)

PdfChatResult = PdfChatSuccess | PdfChatNoContent | PdfChatNoRelevantDocs | PdfChatFailure


def _build_context(chunks: list[RetrievedChunk], *, limit: int = 3) -> str:
    """Format retrieved chunks into a single context string."""
    parts: list[str] = []
    for chunk in chunks[:limit]:
        page = chunk.metadata.get("page", "Unknown")
        parts.append(f"Page {page}: {chunk.content}")
    return "\n\n".join(parts)


class PdfChatUseCase(CommandHandler[PdfChatCommand]):
    """Framework-free orchestration of a PDF chat message.

    Uses hybrid search (BM25 + vector) with cross-encoder reranking
    for higher-quality retrieval.  When no reranker is provided, falls
    back to plain retrieval ordering.
    """

    def __init__(
        self,
        *,
        llm: LlmPort,
        vector_store: VectorStorePort,
        reranker: RerankerPort | None = None,
    ) -> None:
        self._llm = llm
        self._vector_store = vector_store
        self._reranker = reranker

    def handle(self, command: PdfChatCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command)

    # ── public entry point ────────────────────────────────────────────

    def execute(self, command: PdfChatCommand) -> PdfChatResult:
        filters = {
            "pdf_id": command.pdf_id,
            "workspace_id": command.workspace_id,
            "user_id": str(command.user_id),
        }

        # 1. Existence check
        if not self._vector_store.has_indexed_content(
            pdf_id=command.pdf_id,
            workspace_id=command.workspace_id,
            user_id=str(command.user_id),
        ):
            return PdfChatNoContent(
                pdf_id=command.pdf_id,
                workspace_id=command.workspace_id,
            )

        # 2. Retrieve chunks (hybrid search with fallback)
        chunks = self._retrieve_with_fallback(command.query, filters)

        if not chunks:
            return PdfChatNoRelevantDocs(
                pdf_id=command.pdf_id,
                workspace_id=command.workspace_id,
            )

        # 3. Detect intent
        intent = detect_pdf_intent(command.query)

        # 4-6. Build prompt + invoke LLM
        try:
            if intent.kind in ("tldr", "summary"):
                return self._handle_summary(command, intent, filters)
            return self._handle_qa(command, chunks)
        except Exception as exc:
            return PdfChatFailure(error=str(exc))

    # ── retrieval with hybrid search + reranking ─────────────────────

    def _retrieve_with_fallback(
        self, query: str, filters: dict
    ) -> list[RetrievedChunk]:
        """Hybrid search → rerank → fallback to keyword → broad."""

        # Strategy 0: hybrid search (BM25 + vector)
        # Over-fetch then rerank for better precision
        fetch_k = 20 if self._reranker else 5
        chunks = self._vector_store.hybrid_search(
            query,
            k=fetch_k,
            filters=filters,
            mode=SearchMode.HYBRID,
        )

        if chunks:
            return self._rerank(query, chunks, top_k=5)

        # Strategy 1: individual non-stop-words (keyword fallback)
        for word in extract_search_words(query):
            word_chunks = self._vector_store.hybrid_search(
                word,
                k=fetch_k,
                filters=filters,
                mode=SearchMode.KEYWORD,
            )
            if word_chunks:
                return self._rerank(query, word_chunks, top_k=5)

        # Strategy 2: broad space query
        broad = self._vector_store.search(" ", k=5, filters=filters)
        return broad[:5]

    def _rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Rerank chunks if a reranker is available, otherwise return as-is."""
        if self._reranker is None:
            return chunks[:top_k]
        try:
            return self._reranker.rerank(query, chunks, top_k=top_k)
        except Exception:
            logger.warning("Reranker failed, returning raw retrieval order", exc_info=True)
            return chunks[:top_k]

    # ── summary / tldr path ───────────────────────────────────────────

    def _handle_summary(
        self,
        command: PdfChatCommand,
        intent: PdfIntent,
        filters: dict,
    ) -> PdfChatSuccess | PdfChatFailure:
        # Grab more chunks for comprehensive summary
        all_chunks = self._vector_store.search(" ", k=10, filters=filters)
        if not all_chunks:
            return PdfChatFailure(
                error=f"Could not find content in document {command.pdf_id} to summarize."
            )

        context = _build_context(all_chunks, limit=10)
        enhanced = (
            "This document contains information about the subject matter discussed.\n\n"
            + context
        )

        if intent.kind == "tldr":
            prompt = build_pdf_tldr_prompt(enhanced, words=150)
        else:
            prompt = build_pdf_summary_prompt(enhanced, max_length=500)

        result = self._llm.invoke(prompt)
        return PdfChatSuccess(
            content=result.content,
            model=result.model,
            usage=result.usage,
        )

    # ── Q&A path ──────────────────────────────────────────────────────

    def _handle_qa(
        self,
        command: PdfChatCommand,
        chunks: list[RetrievedChunk],
    ) -> PdfChatSuccess | PdfChatFailure:
        context = _build_context(chunks, limit=3)
        enhanced = (
            "This document contains information about the subject matter discussed.\n\n"
            + context
        )

        history_context = (
            "\n".join(command.chat_history) if command.chat_history else "No previous conversation."
        )

        prompt = build_pdf_qa_prompt(
            history_context=history_context,
            context=enhanced,
            pdf_id=command.pdf_id,
            input_text=command.query,
        )

        result = self._llm.invoke(prompt)
        return PdfChatSuccess(
            content=result.content,
            model=result.model,
            usage=result.usage,
        )

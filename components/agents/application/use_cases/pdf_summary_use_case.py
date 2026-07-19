"""Use case: generate a standalone summary of a PDF document.

Extracts the business logic from the ``summarize_pdf`` controller endpoint:
    1. Verify indexed content exists
    2. Retrieve broad chunks
    3. Build summary prompt
    4. Invoke LLM
    5. Return structured result with word count / chunk stats

Framework-free — no Django, DRF, or ORM imports.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.commands.pdf_summary_command import (
    PdfSummaryCommand,
    PdfSummaryFailure,
    PdfSummaryNoContent,
    PdfSummarySuccess,
)
from components.knowledge.application.ports.llm_port import LlmPort
from components.knowledge.application.ports.vector_store_port import VectorStorePort
from components.shared_kernel.application.handlers import CommandHandler

from components.agents.domain.value_objects.pdf_prompts import build_pdf_summary_prompt


PdfSummaryResult = PdfSummarySuccess | PdfSummaryNoContent | PdfSummaryFailure


class PdfSummaryUseCase(CommandHandler[PdfSummaryCommand]):
    """Framework-free orchestration of a PDF summary request."""

    def __init__(self, *, llm: LlmPort, vector_store: VectorStorePort) -> None:
        self._llm = llm
        self._vector_store = vector_store

    def handle(self, command: PdfSummaryCommand) -> Any:
        """CommandHandler implementation."""
        return self.execute(command)

    def execute(self, command: PdfSummaryCommand) -> PdfSummaryResult:
        filters = {
            "pdf_id": command.pdf_id,
            "workspace_id": command.workspace_id,
            "user_id": command.user_id,
        }

        # 1. Existence check
        if not self._vector_store.has_indexed_content(
            pdf_id=command.pdf_id,
            workspace_id=command.workspace_id,
            user_id=command.user_id,
        ):
            return PdfSummaryNoContent(
                pdf_id=command.pdf_id,
                workspace_id=command.workspace_id,
            )

        # 2. Retrieve broad chunks for summary
        chunks = self._vector_store.search(
            "summary overview content", k=50, filters=filters
        )
        if not chunks:
            return PdfSummaryNoContent(
                pdf_id=command.pdf_id,
                workspace_id=command.workspace_id,
            )

        full_content = "\n\n".join(c.content for c in chunks)

        # 3. Build prompt + invoke LLM
        prompt = build_pdf_summary_prompt(
            full_content=full_content, max_length=command.max_length
        )
        try:
            result = self._llm.invoke(prompt)
            summary = result.content
        except Exception as exc:
            return PdfSummaryFailure(error=f"Error generating summary: {exc}")

        return PdfSummarySuccess(
            summary=summary,
            total_chunks=len(chunks),
            word_count=len(summary.split()),
            max_length=command.max_length,
            model=result.model,
            usage=result.usage,
        )

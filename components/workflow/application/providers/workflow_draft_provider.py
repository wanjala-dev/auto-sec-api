"""Composition root for AI-assisted workflow drafting.

Wires the concrete LLM adapter to the ``DraftWorkflowGraphUseCase``. Providers
own this policy decision (which adapter implements the port), so the API layer
just asks for a ready use case.
"""

from __future__ import annotations

from components.workflow.application.use_cases.draft_workflow_graph_use_case import (
    DraftWorkflowGraphUseCase,
)


class WorkflowDraftProvider:
    @staticmethod
    def build_draft_use_case() -> DraftWorkflowGraphUseCase:
        from components.workflow.infrastructure.adapters.langchain_workflow_draft_adapter import (
            LangchainWorkflowDraftAdapter,
        )

        return DraftWorkflowGraphUseCase(draft_port=LangchainWorkflowDraftAdapter())

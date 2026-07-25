"""LLM adapter for AI-assisted workflow drafting.

Implements ``WorkflowDraftPort`` via the shared knowledge LLM provider
(``AILlmProvider`` → ``LlmPort``), the same backend the rest of the AI surface
uses. Kept deliberately thin: it performs one chat completion and returns the
raw text; the JSON parsing + validate-and-repair loop live in the use case.
"""

from __future__ import annotations

import logging

from components.workflow.application.ports.workflow_draft_port import WorkflowDraftPort

logger = logging.getLogger(__name__)

# Low temperature — we want a valid, deterministic graph, not creative prose.
_TEMPERATURE = 0.2


class LangchainWorkflowDraftAdapter(WorkflowDraftPort):
    def is_configured(self) -> bool:
        try:
            from components.knowledge.application.providers.ai_llm_provider import (  # noqa: F401
                AILlmProvider,
            )
        except ImportError:
            return False
        # An adapter is only usable if a provider key is actually present.
        import os

        return bool(
            os.environ.get("OPENAI_API_KEY")
            or (os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_API_BASE"))
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        from components.knowledge.application.providers.ai_llm_provider import (
            AILlmProvider,
        )

        port = AILlmProvider().get_default_port(temperature=_TEMPERATURE)
        response = port.chat(messages)
        return (response.content or "").strip()

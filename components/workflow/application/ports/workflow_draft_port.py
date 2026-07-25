"""Port for AI-assisted workflow drafting.

The application core asks a language model to turn a natural-language prompt
into a workflow graph. It depends on THIS interface, never on an LLM SDK — the
adapter (``infrastructure/adapters/langchain_workflow_draft_adapter.py``) wires
the concrete provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class WorkflowDraftPort(ABC):
    """Generate raw model text from role-based chat messages."""

    @abstractmethod
    def is_configured(self) -> bool:
        """True when an LLM backend is available in this environment."""
        ...

    @abstractmethod
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return the model's text for a list of {role, content} messages.

        The use case owns the JSON parsing + validate-and-repair loop; the
        adapter only performs the completion.
        """
        ...

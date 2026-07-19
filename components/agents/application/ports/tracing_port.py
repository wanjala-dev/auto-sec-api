"""
Port for agent execution tracing / observability.

Any observability backend (Langfuse, LangSmith, Datadog, OpenTelemetry, etc.)
implements this port so the agent runtime can attach tracing without coupling
to a specific vendor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class TracingPort(ABC):
    """
    Contract for agent-execution observability providers.

    The primary integration point is ``get_langchain_callback`` which returns
    a LangChain-compatible ``BaseCallbackHandler`` (or *None* when tracing is
    unavailable).  This keeps the agent executor vendor-agnostic — it only
    knows it receives an optional callback.

    Secondary helpers (``trace_conversation``, ``trace_llm_call``,
    ``trace_retrieval``) exist for manual span creation outside the LangChain
    callback pipeline.
    """

    # ------------------------------------------------------------------
    # Core capability — LangChain callback integration
    # ------------------------------------------------------------------

    @abstractmethod
    def is_available(self) -> bool:
        """Return *True* when the backend is configured and reachable."""

    @abstractmethod
    def get_langchain_callback(
        self,
        *,
        agent_id: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Build a LangChain ``BaseCallbackHandler`` wired to the tracing backend.

        Returns *None* when the backend is unavailable so callers can safely
        skip without branching on vendor details.
        """

    # ------------------------------------------------------------------
    # Manual span helpers (optional — default to no-ops)
    # ------------------------------------------------------------------

    def trace_conversation(
        self,
        conversation_id: str,
        user_id: str,
        **metadata: Any,
    ) -> Optional[Any]:
        """Start a top-level trace/span for a conversation."""
        return None

    def trace_llm_call(
        self,
        trace: Any,
        model_name: str,
        input_text: str,
        **metadata: Any,
    ) -> Optional[Any]:
        """Record an LLM generation inside an existing trace."""
        return None

    def trace_retrieval(
        self,
        trace: Any,
        query: str,
        documents: list,
        **metadata: Any,
    ) -> Optional[Any]:
        """Record a retrieval span inside an existing trace."""
        return None


class NullTracingAdapter(TracingPort):
    """
    No-op adapter used when no tracing backend is configured.

    This avoids littering call-sites with ``if tracer is not None`` checks.
    """

    def is_available(self) -> bool:
        return False

    def get_langchain_callback(self, *, agent_id, user_id, session_id=None):
        return None

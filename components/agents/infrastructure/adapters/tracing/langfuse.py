"""
Langfuse adapter for the TracingPort.

Encapsulates ALL Langfuse-specific logic so swapping to LangSmith, Datadog,
or any other tracing backend only requires writing a new adapter — no changes
to the agent runtime.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from django.conf import settings

from components.agents.application.ports.tracing_port import TracingPort

logger = logging.getLogger(__name__)


def _resolve_setting(django_attr: str, *env_names: str, default: str = "") -> str:
    """Read from Django settings first, then env vars, then default."""
    value = getattr(settings, django_attr, None)
    if value:
        return str(value).strip()
    for env in env_names:
        value = os.getenv(env)
        if value and value.strip():
            return value.strip()
    return default


class LangfuseTracingAdapter(TracingPort):
    """
    Langfuse implementation of :class:`TracingPort`.

    All ``langfuse`` imports are deferred so the adapter degrades gracefully
    when the library or credentials are absent.
    """

    def __init__(self) -> None:
        self._langfuse: Any = None
        self._available: bool = self._probe()
        if self._available:
            self._connect()

    # ------------------------------------------------------------------
    # TracingPort — core
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return self._available

    def get_langchain_callback(
        self,
        *,
        agent_id: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        if not self._available:
            return None
        try:
            from langfuse.callback import CallbackHandler

            return CallbackHandler(
                public_key=_resolve_setting("LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
                secret_key=_resolve_setting("LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
                host=self._resolve_host(),
                session_id=session_id,
                user_id=user_id,
            )
        except Exception:
            logger.exception("Failed to build Langfuse CallbackHandler for agent %s", agent_id)
            return None

    # ------------------------------------------------------------------
    # TracingPort — manual spans
    # ------------------------------------------------------------------

    def trace_conversation(
        self,
        conversation_id: str,
        user_id: str,
        **metadata: Any,
    ) -> Optional[Any]:
        if not self._available or self._langfuse is None:
            return None
        try:
            return self._langfuse.trace(
                name="ai_conversation",
                id=conversation_id,
                user_id=user_id,
                metadata=metadata,
            )
        except Exception:
            logger.exception("Failed to create Langfuse trace for conversation %s", conversation_id)
            return None

    def trace_llm_call(
        self,
        trace: Any,
        model_name: str,
        input_text: str,
        **metadata: Any,
    ) -> Optional[Any]:
        if not self._available or trace is None:
            return None
        try:
            return trace.generation(
                name="llm_call",
                model=model_name,
                input=input_text,
                metadata=metadata,
            )
        except Exception:
            logger.exception("Failed to create Langfuse LLM generation span")
            return None

    def trace_retrieval(
        self,
        trace: Any,
        query: str,
        documents: list,
        **metadata: Any,
    ) -> Optional[Any]:
        if not self._available or trace is None:
            return None
        try:
            return trace.span(
                name="retrieval",
                input=query,
                output=documents,
                metadata=metadata,
            )
        except Exception:
            logger.exception("Failed to create Langfuse retrieval span")
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _probe(self) -> bool:
        """Check whether Langfuse is importable and credentials are present."""
        try:
            import langfuse  # noqa: F401
        except ImportError:
            return False

        public = _resolve_setting("LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY")
        secret = _resolve_setting("LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY")
        available = bool(public and secret)
        if not available:
            logger.debug(
                "Langfuse credentials missing (public_key=%s, secret_key=%s)",
                bool(public),
                bool(secret),
            )
        return available

    def _connect(self) -> None:
        """Lazily initialize the Langfuse client."""
        try:
            from langfuse import Langfuse

            self._langfuse = Langfuse(
                public_key=_resolve_setting("LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
                secret_key=_resolve_setting("LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
                host=self._resolve_host(),
            )
        except Exception:
            logger.warning("Failed to initialise Langfuse client", exc_info=True)
            self._available = False

    @staticmethod
    def _resolve_host() -> str:
        return _resolve_setting(
            "LANGFUSE_HOST",
            "LANGFUSE_HOST",
            "LANGFUSE_BASE_URL",
            default="http://127.0.0.1:3100",
        )

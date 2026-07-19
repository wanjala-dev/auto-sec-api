"""
Langfuse adapter for the TracingPort — langfuse SDK 3.x (OTEL-based).

Encapsulates ALL Langfuse-specific logic so swapping to LangSmith, Datadog,
or any other tracing backend only requires writing a new adapter — no changes
to the agent runtime.

SDK 3.x migration notes (langfuse==3.15.0, pinned in requirements/base.txt):

- The LangChain handler moved from ``langfuse.callback.CallbackHandler`` to
  ``langfuse.langchain.CallbackHandler`` and no longer accepts credentials or
  ``session_id`` / ``user_id`` in its constructor. Credentials live on the
  ``Langfuse`` client (a per-public-key singleton registry); the handler binds
  to a registered client via ``public_key``.
- Trace attributes (session/user) are read from run metadata keys
  (``langfuse_session_id`` / ``langfuse_user_id``). The agent runtime does not
  thread metadata through the graph config — it sets ``callback.session_id``
  directly and calls ``callback.flush()`` (duck-typed seams in
  ``BaseAgent.execute``). ``_SessionAwareCallbackHandler`` below restores both
  seams on top of the 3.x API.
- The 2.x stateful low-level API (``client.trace()`` / ``trace.generation()``
  / ``trace.span()``) is gone; the manual span helpers now use the 3.x
  observation API (``start_span`` / ``start_generation`` / ``update_trace``).
"""

from __future__ import annotations

import logging
import os
from typing import Any

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


# Lazily-built subclass cache so this module imports cleanly when the
# ``langfuse`` package is absent (degrade discipline: the adapter must never
# crash a run because tracing is unavailable).
_handler_cls: Any = None


def _session_aware_handler_cls() -> Any:
    """Build (once) the session-aware LangChain callback handler subclass."""
    global _handler_cls
    if _handler_cls is not None:
        return _handler_cls

    from langfuse.langchain import CallbackHandler

    class _SessionAwareCallbackHandler(CallbackHandler):
        """3.x LC handler carrying session/user defaults for the agent runtime.

        langfuse 3.x reads trace attributes from run metadata
        (``langfuse_session_id`` / ``langfuse_user_id``) instead of handler
        constructor kwargs. ``BaseAgent.execute`` doesn't pass metadata through
        the graph config; it mutates ``callback.session_id`` before a run and
        calls ``callback.flush()`` after. This subclass restores both seams:

        - ``_parse_langfuse_trace_attributes_from_metadata`` falls back to the
          instance-level ``session_id`` / ``user_id`` when run metadata carries
          no explicit ``langfuse_*`` keys (explicit metadata still wins).
        - ``flush()`` delegates to the underlying ``Langfuse`` client.

        The attribute-fallback overrides a private hook of the PINNED
        ``langfuse==3.15.0`` — re-verify on any langfuse version bump.
        """

        def __init__(
            self,
            *,
            public_key: str | None = None,
            session_id: str | None = None,
            user_id: str | None = None,
        ) -> None:
            # update_trace=True mirrors the 2.x handler behaviour of setting
            # trace-level input/output/name from the root chain run.
            super().__init__(public_key=public_key, update_trace=True)
            self.session_id = session_id
            self.user_id = user_id

        def _parse_langfuse_trace_attributes_from_metadata(self, metadata):
            attributes = super()._parse_langfuse_trace_attributes_from_metadata(metadata)
            if "session_id" not in attributes and self.session_id:
                attributes["session_id"] = str(self.session_id)
            if "user_id" not in attributes and self.user_id:
                attributes["user_id"] = str(self.user_id)
            return attributes

        def flush(self) -> None:
            """Flush queued spans to the Langfuse server (agent-runtime seam)."""
            self.client.flush()

    _handler_cls = _SessionAwareCallbackHandler
    return _handler_cls


class LangfuseTracingAdapter(TracingPort):
    """
    Langfuse implementation of :class:`TracingPort`.

    All ``langfuse`` imports are deferred so the adapter degrades gracefully
    when the library or credentials are absent.
    """

    def __init__(self) -> None:
        self._langfuse: Any = None
        self._public_key: str = ""
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
        session_id: str | None = None,
    ) -> Any | None:
        if not self._available or self._langfuse is None:
            return None
        try:
            handler_cls = _session_aware_handler_cls()
            return handler_cls(
                public_key=self._public_key,
                session_id=session_id,
                user_id=str(user_id) if user_id else None,
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
    ) -> Any | None:
        if not self._available or self._langfuse is None:
            return None
        try:
            # Deterministic trace id derived from the conversation id keeps the
            # 2.x semantic of trace-per-conversation (v3 requires W3C ids).
            trace_id = self._langfuse.create_trace_id(seed=str(conversation_id))
            span = self._langfuse.start_span(
                trace_context={"trace_id": trace_id},
                name="ai_conversation",
                metadata=metadata or None,
            )
            span.update_trace(
                name="ai_conversation",
                user_id=str(user_id) if user_id else None,
                session_id=str(conversation_id),
                metadata=metadata or None,
            )
            return span
        except Exception:
            logger.exception("Failed to create Langfuse trace for conversation %s", conversation_id)
            return None

    def trace_llm_call(
        self,
        trace: Any,
        model_name: str,
        input_text: str,
        **metadata: Any,
    ) -> Any | None:
        if not self._available or trace is None:
            return None
        try:
            return trace.start_generation(
                name="llm_call",
                model=model_name,
                input=input_text,
                metadata=metadata or None,
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
    ) -> Any | None:
        if not self._available or trace is None:
            return None
        try:
            return trace.start_span(
                name="retrieval",
                input=query,
                output=documents,
                metadata=metadata or None,
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
        """Initialize (and globally register) the Langfuse 3.x client."""
        try:
            from langfuse import Langfuse

            self._public_key = _resolve_setting("LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY")
            # Registers a per-public-key singleton client; the LangChain
            # handler binds to it via ``public_key`` (3.x resolves credentials
            # on the client, never on the handler).
            self._langfuse = Langfuse(
                public_key=self._public_key,
                secret_key=_resolve_setting("LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
                host=self._resolve_host(),
            )
        except Exception:
            logger.warning("Failed to initialise Langfuse client", exc_info=True)
            self._langfuse = None
            self._available = False

    @staticmethod
    def _resolve_host() -> str:
        return _resolve_setting(
            "LANGFUSE_HOST",
            "LANGFUSE_HOST",
            "LANGFUSE_BASE_URL",
            default="http://127.0.0.1:3100",
        )

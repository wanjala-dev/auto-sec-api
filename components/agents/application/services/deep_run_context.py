"""DeepRunContext — the in-tool API for emitting log + progress events.

This is the application-layer hook that long-running tools (RAG
retrieval, report generation, document import, Stripe round-trips,
etc.) call mid-execution to surface narrative log lines and granular
progress updates. The shape is borrowed from MCP's ``Context.info()``
and ``Context.report_progress()`` so future MCP wire-format
compatibility is a small step rather than a rewrite.

Pure application code — no Django, no ORM, no Celery imports. The
context delegates to a ``DeepRunObservabilityPort`` instance that the
infrastructure layer wires up at run start. Side effects (persisting
``DeepRunLog`` rows, publishing to the WebSocket channel) live in the
adapter; this class only translates the in-tool API into port calls.

Tools accept ``ctx: DeepRunContext`` as a keyword-only argument that
defaults to ``NoopDeepRunContext()`` so callers running outside a deep
run (CLI commands, unit tests, ad-hoc invocation) don't have to know
or care about run lifecycle. Inside a deep run, the
``deep.runner.execute_plan_once`` builds a real context with the live
``thread_id`` and threads it through ``AgentService.execute_agent``
(via ``context["deep_run_context"]``).

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.agents.application.ports.deep_run_observability_port import (
    DeepRunObservabilityPort,
)


@dataclass(frozen=True)
class DeepRunContextOptions:
    """Frozen identity of the run a context speaks for.

    ``thread_id`` is the canonical key — every emit uses it to find the
    matching ``DeepRun`` row. The other fields are denormalised
    convenience for tools that want to attach the active agent / tool
    name to every emit without passing it on each call.
    """

    thread_id: str | None
    default_agent_type: str | None = None
    default_tool_name: str | None = None


class DeepRunContext:
    """In-tool API for emitting log + progress events to the chat UI.

    Construct via ``DeepRunContext(port, options)``. Tools receive an
    instance and call ``info()`` / ``warn()`` / ``report_progress()``
    while they work; the port handles persistence + transport. Both
    methods are sync — emit is fire-and-forget from the tool's
    perspective.
    """

    def __init__(
        self,
        port: DeepRunObservabilityPort,
        options: DeepRunContextOptions,
    ) -> None:
        self._port = port
        self._options = options

    def info(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a narrative log line at "info" severity.

        ``payload`` is merged into the event payload — use it for
        structured data the renderer might want (counts, durations,
        sample IDs). Avoid putting large blobs here; the WebSocket
        envelope and DeepRunLog row are best kept small.
        """
        self._port.emit_log(
            thread_id=self._options.thread_id,
            message=message,
            tool_name=tool_name or self._options.default_tool_name,
            agent_type=self._options.default_agent_type,
            severity="info",
            payload=payload,
        )

    def warn(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a narrative log line at "warn" severity.

        Reserved for soft-failure cases — "third API retry succeeded",
        "skipped 2 unparseable rows", "vector store returned 0 hits".
        Never use ``warn()`` for hard failures; raise from the tool
        instead so the run records the proper ``worker_failed`` event.
        """
        self._port.emit_log(
            thread_id=self._options.thread_id,
            message=message,
            tool_name=tool_name or self._options.default_tool_name,
            agent_type=self._options.default_agent_type,
            severity="warn",
            payload=payload,
        )

    def report_progress(
        self,
        current: float,
        total: float | None = None,
        *,
        message: str | None = None,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a progress update.

        ``current`` is the absolute progress; ``total`` is the
        denominator. Pass ``total=None`` for indeterminate progress —
        the renderer falls back to "Step N" without a percentage. When
        ``total`` is set the adapter computes an integer
        ``progress_percent`` and attaches it to the payload.
        """
        self._port.emit_progress(
            thread_id=self._options.thread_id,
            current=current,
            total=total,
            message=message,
            tool_name=tool_name or self._options.default_tool_name,
            agent_type=self._options.default_agent_type,
            payload=payload,
        )


class NoopDeepRunContext(DeepRunContext):
    """No-op context for callers running outside a live deep run.

    Used as the default value for ``ctx`` arguments on tool functions so
    callers don't have to special-case the "not in a run" path. Every
    emit is dropped silently — no port call, no exception.

    Constructing this directly skips the port and options requirement;
    every method is overridden to do nothing.
    """

    def __init__(self) -> None:  # noqa: D401 — intentional no-arg shape
        # Skip super().__init__ — we don't need a port reference.
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        return None

    def warn(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        return None

    def report_progress(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        return None


_NOOP_SINGLETON = NoopDeepRunContext()


def noop_context() -> DeepRunContext:
    """Return the shared no-op context singleton.

    Tools can use this as their default kwarg without paying the cost
    of constructing a fresh no-op every call:

        def my_tool(query: str, *, ctx: DeepRunContext = noop_context()):
            ...
    """
    return _NOOP_SINGLETON

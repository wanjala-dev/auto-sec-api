"""Port for emitting mid-execution log + progress events from a deep run.

The application-layer ``DeepRunContext`` (see
``components/agents/application/services/deep_run_context.py``) collects
``info()`` / ``warn()`` / ``report_progress()`` calls from inside tool
code and dispatches them through this port. Implementations live in
``components/agents/infrastructure/adapters/`` and are responsible for
the actual persistence / pub-sub side effects.

Two event types are emitted: ``tool_log`` for narrative log lines,
``tool_progress`` for granular progress updates. Both are delivered to
the same ``DeepRunLog`` table and the same WebSocket channel as the
existing ``run_started`` / ``worker_started`` / etc. events — see
``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` for the full
flow.

Failure mode: emit calls must NEVER raise into the tool that called
them. A broken observability layer should not crash a working tool.
Adapters log and swallow exceptions inside their implementations.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ── Event-type constants ────────────────────────────────────────────────
#
# Kept here (not on the persistence model) because the application layer
# emits them and the persistence layer just stores whatever string the
# emitter passes. Keeping the constants in the port file means tools and
# tests share a single source of truth, and the persistence layer doesn't
# constrain the application vocabulary.

EVENT_TOOL_LOG = "tool_log"
EVENT_TOOL_PROGRESS = "tool_progress"


class DeepRunObservabilityPort(ABC):
    """Interface for delivering mid-tool log + progress events.

    Two methods, one per event type, both keyword-only. Implementations
    must be safe to call with a missing or unknown ``thread_id`` — when
    no live deep run matches, the emit is a silent no-op (callers
    should not have to know whether they're inside a deep run or not).
    """

    @abstractmethod
    def emit_log(
        self,
        *,
        thread_id: str | None,
        message: str,
        tool_name: str | None = None,
        agent_type: str | None = None,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a narrative log line ("tool_log" event).

        ``severity`` is "info" / "warn" / "debug" — surfaces in the
        rendered console block as styling, does not change persistence
        or transport.
        """

    @abstractmethod
    def emit_progress(
        self,
        *,
        thread_id: str | None,
        current: float,
        total: float | None = None,
        message: str | None = None,
        tool_name: str | None = None,
        agent_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a progress update ("tool_progress" event).

        ``current`` is the absolute progress number; ``total`` is the
        denominator (for "X of Y" rendering). When ``total`` is set the
        adapter computes an integer ``progress_percent`` and includes
        it in the payload so consumers can drive a progress bar
        without recomputing.
        """

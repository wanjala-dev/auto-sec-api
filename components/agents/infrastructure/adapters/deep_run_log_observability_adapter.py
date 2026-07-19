"""Adapter — fulfils ``DeepRunObservabilityPort`` via the existing
``log_deep_event`` helper.

Every emit becomes a ``DeepRunLog`` insert keyed by ``thread_id``. The
already-installed ``DjangoDeepRunRealtimeSignalBridge`` watches
``DeepRunLog.post_save`` and publishes a ``resource.event`` envelope to
the per-run WebSocket channel — so this adapter doesn't need to know
about Channels, Redis, or the realtime layer at all. It just writes to
the log, and the bridge does the rest.

Failure isolation is load-bearing: a tool that emits a log line should
not crash because the observability stack is degraded. ``log_deep_event``
already swallows exceptions internally; we wrap our own work in
try/except too so any future expansion (extra adapters, fan-out)
preserves the contract.

See ``docs/plans/CHAT_LOG_AND_PROGRESS_NOTIFICATIONS_PLAN.md`` Phase 1.
"""
from __future__ import annotations

import logging
from typing import Any

from components.agents.application.ports.deep_run_observability_port import (
    EVENT_TOOL_LOG,
    EVENT_TOOL_PROGRESS,
    DeepRunObservabilityPort,
)

logger = logging.getLogger(__name__)


class DeepRunLogObservabilityAdapter(DeepRunObservabilityPort):
    """Persists emit calls as ``DeepRunLog`` rows so the existing
    realtime signal bridge picks them up. No constructor args — the
    adapter is stateless and a singleton is fine.
    """

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
        # No live thread → silent drop. ``log_deep_event`` would do
        # the same internally, but checking here saves the import +
        # ORM dispatch cost for tools that fire many events.
        if not thread_id:
            return
        merged_payload: dict[str, Any] = {
            "message": message,
            "severity": severity,
        }
        if payload:
            merged_payload.update(payload)
        try:
            from components.agents.infrastructure.gateways.deep.logging import (
                log_deep_event,
            )

            log_deep_event(
                thread_id,
                EVENT_TOOL_LOG,
                agent_type=agent_type,
                tool_name=tool_name,
                payload=merged_payload,
            )
        except Exception:
            # Adapter is the last line of defence — never let a
            # broken realtime layer surface inside the calling tool.
            logger.exception(
                "deep_run_observability_emit_log_failed thread_id=%s "
                "tool_name=%s",
                thread_id,
                tool_name,
            )

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
        if not thread_id:
            return
        merged_payload: dict[str, Any] = {
            "current": float(current),
            "total": float(total) if total is not None else None,
        }
        # Pre-compute progress_percent so the WebSocket consumer can
        # drive the bar without recomputing. The signal bridge already
        # plucks ``progress_percent`` out of the payload to populate
        # the envelope's top-level field.
        if total and total > 0:
            try:
                merged_payload["progress_percent"] = max(
                    0, min(100, int(round((current / total) * 100)))
                )
            except (TypeError, ValueError):
                # Non-numeric inputs — skip the percent rather than
                # raise. The renderer will cope with a missing value.
                pass
        if message:
            merged_payload["message"] = message
        if payload:
            merged_payload.update(payload)
        try:
            from components.agents.infrastructure.gateways.deep.logging import (
                log_deep_event,
            )

            log_deep_event(
                thread_id,
                EVENT_TOOL_PROGRESS,
                agent_type=agent_type,
                tool_name=tool_name,
                payload=merged_payload,
            )
        except Exception:
            logger.exception(
                "deep_run_observability_emit_progress_failed thread_id=%s "
                "tool_name=%s",
                thread_id,
                tool_name,
            )

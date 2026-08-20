"""ADR 0031 D3 — ``ToolGovernanceMiddleware``, Phase 1 (observe-only).

``create_agent(..., middleware=self._build_agent_middleware())`` was already
wired at ``base.py``; the method returned an empty list. There is a wired,
empty middleware chain in front of every tool call on every agent, and unlike
the promotion-loop wrappers (``_risk_gated`` / ``_serialize_tool_result``)
middleware wraps the ``ToolNode`` — so it catches every tool regardless of how
that tool was registered. ``retrieve_workspace_context`` is the proof: it was
constructed directly and received neither wrapper.

**This middleware enforces nothing.** It classifies and records:

- per-tool **latency**, which is measured today and then discarded;
- per-tool **outcome**, which is the bit ``_serialize_tool_result`` flattens
  into a string before anything can read it — ``ToolResult(ok=False)`` becomes
  ``"Error: ..."`` and the failure disappears;
- the value for ``DeepRunLog.status``, a column that exists and is never
  written.

Recovering that bit is the point of Phase 1, not a side effect. The worked
failure it makes visible: an LLM-provider outage produces "reviewed; no
confident fix" across every finding, every card stamped triaged, and
``status="completed"`` at all four layers. After this middleware the tool
observations carry ``outcome=failure`` and the run logs a warning that it
reported success over failed tool calls. The reported status does not change —
that is Phase 3 — but it stops being invisible.

Reversible by removing one entry from the list ``_build_agent_middleware``
returns.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from components.agents.application.policies.tool_spec import (
    TOOL_RESULT_ERROR_PREFIX,
    Failure,
    ToolCallObservation,
    ToolOutcome,
    ToolSpec,
    classify_exception,
)

logger = logging.getLogger(__name__)

#: Cap on retained observations per agent instance. A run is bounded by
#: ``max_tool_calls`` (default 40), so this only guards against an agent
#: instance being reused across many turns without ``execute()`` draining it.
_MAX_RETAINED_OBSERVATIONS = 500


class ToolCallObservationBuffer:
    """Per-agent store of the current turn's tool-call observations.

    Keyed by ``tool_call_id`` so ``_persist_tool_observations`` can join a
    middleware observation onto the ``tool_observation`` row it already writes,
    rather than emitting a second row per tool call.
    """

    def __init__(self) -> None:
        self._by_call_id: dict[str, ToolCallObservation] = {}
        self._ordered: list[ToolCallObservation] = []

    def record(self, observation: ToolCallObservation) -> None:
        if len(self._ordered) >= _MAX_RETAINED_OBSERVATIONS:
            # Drop the oldest rather than grow without bound. Losing the head
            # of a 500-call turn is strictly better than an unbounded dict.
            oldest = self._ordered.pop(0)
            self._by_call_id.pop(oldest.tool_call_id, None)
        self._ordered.append(observation)
        if observation.tool_call_id:
            self._by_call_id[observation.tool_call_id] = observation

    def get(self, tool_call_id: str | None) -> ToolCallObservation | None:
        if not tool_call_id:
            return None
        return self._by_call_id.get(tool_call_id)

    def all(self) -> list[ToolCallObservation]:
        return list(self._ordered)

    def failures(self) -> list[ToolCallObservation]:
        return [obs for obs in self._ordered if obs.failed]

    def summary(self) -> dict[str, Any]:
        """Aggregate counts for the run-telemetry payload."""
        observations = self._ordered
        if not observations:
            return {}
        failures = [obs for obs in observations if obs.failed]
        latencies = [obs.latency_ms for obs in observations]
        summary: dict[str, Any] = {
            "calls": len(observations),
            "failed": len(failures),
            "undeclared": sum(1 for obs in observations if not obs.declared),
            "total_latency_ms": sum(latencies),
            "max_latency_ms": max(latencies),
        }
        if failures:
            by_failure: dict[str, int] = {}
            for obs in failures:
                by_failure[obs.failure or Failure.INTERNAL] = by_failure.get(obs.failure or Failure.INTERNAL, 0) + 1
            summary["failures_by_reason"] = by_failure
            summary["failed_tools"] = sorted({obs.tool_name for obs in failures})
        return summary

    def clear(self) -> None:
        self._by_call_id.clear()
        self._ordered.clear()


def classify_tool_message(message: Any) -> tuple[str, str | None]:
    """Classify a returned ``ToolMessage`` into ``(outcome, failure)``.

    Two signals, in order:

    1. LangChain's own ``ToolMessage.status`` — set to ``"error"`` when the
       ``ToolNode`` caught an exception out of the tool body.
    2. The ``"Error: "`` prefix ``ToolResult.serialize()`` renders for
       ``ok=False``. This is the recovery of the flattened bit: the framework
       already knew the call failed and threw the knowledge away at
       ``_serialize_tool_result``. Reading it back off the rendered string is
       not elegant, and it is deliberately not a fix — D2 makes the structured
       result reach the middleware directly. Until then this is the only place
       the bit still exists, and observing it is what sizes D2.
    """
    if not isinstance(message, ToolMessage):
        return ToolOutcome.SUCCESS, None

    if getattr(message, "status", None) == "error":
        return ToolOutcome.FAILURE, Failure.INTERNAL

    content = getattr(message, "content", None)
    if isinstance(content, str) and content.lstrip().startswith(TOOL_RESULT_ERROR_PREFIX):
        return ToolOutcome.FAILURE, Failure.INTERNAL

    return ToolOutcome.SUCCESS, None


class ToolGovernanceMiddleware(AgentMiddleware):
    """Observe every tool call. Enforce nothing.

    Phase 3 turns the recorded classifications into gates, one concern at a
    time. Until then the only behavioural contract this class has is that it
    must be transparent: whatever the handler returns is returned unchanged,
    and whatever the handler raises is re-raised unchanged.
    """

    name = "autosec_tool_governance"

    def __init__(self, *, agent: Any, buffer: ToolCallObservationBuffer | None = None) -> None:
        super().__init__()
        self._agent = agent
        self.buffer = buffer if buffer is not None else ToolCallObservationBuffer()

    # ── declaration lookup ────────────────────────────────────────────────

    def spec_for(self, tool_name: str) -> ToolSpec:
        """The declaration for *tool_name*, or the undeclared default.

        Read off ``type(agent)._decorated_tools`` — the same collection the
        promotion loop walks — so a tool's declaration and its registration
        cannot drift apart.
        """
        from components.agents.application.policies.tool_spec import UNDECLARED

        try:
            decorated = getattr(type(self._agent), "_decorated_tools", None) or ()
            for method_name, meta in decorated:
                if (meta.get("name") or method_name) == tool_name:
                    spec = meta.get("spec")
                    return spec if isinstance(spec, ToolSpec) else UNDECLARED
        except Exception:  # pragma: no cover — a broken registry must not break a call
            logger.debug("tool spec lookup failed for %s", tool_name, exc_info=True)
        return UNDECLARED

    # ── the seam ──────────────────────────────────────────────────────────

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        tool_call = request.tool_call if isinstance(request.tool_call, dict) else {}
        tool_name = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or "")

        started = time.perf_counter()
        try:
            result = handler(request)
        except BaseException as exc:
            # Observe-only: classify, record, and re-raise untouched. Letting an
            # implementation bug bubble is the documented contract for
            # ``wrap_tool_call``; this middleware is a licence to classify
            # failures, never to swallow more of them.
            self._record(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                outcome=ToolOutcome.FAILURE,
                failure=classify_exception(exc),
                latency_ms=self._elapsed_ms(started),
            )
            raise

        outcome, failure = classify_tool_message(result)
        self._record(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            outcome=outcome,
            failure=failure,
            latency_ms=self._elapsed_ms(started),
        )
        return result

    # ── recording ─────────────────────────────────────────────────────────

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _record(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        outcome: str,
        failure: str | None,
        latency_ms: int,
    ) -> None:
        """Buffer the observation and log it. Never raises."""
        try:
            spec = self.spec_for(tool_name)
            observation = ToolCallObservation(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                outcome=outcome,
                latency_ms=latency_ms,
                failure=failure,
                declared=spec.is_declared,
                spec_fields=spec.as_log_fields(),
            )
            self.buffer.record(observation)
            # Structured, grep-able, and free of tool input/output — the
            # payload already rides on the tool_observation row and duplicating
            # it here would put tool arguments into the log stream.
            log = logger.warning if observation.failed else logger.info
            log(
                "agent_tool_call tool=%s outcome=%s failure=%s latency_ms=%s declared=%s agent_id=%s workspace_id=%s",
                tool_name,
                outcome,
                failure or "",
                latency_ms,
                spec.is_declared,
                getattr(self._agent, "agent_id", None),
                getattr(self._agent, "workspace_id", None),
            )
        except Exception:  # pragma: no cover — observability never breaks a run
            logger.debug("tool governance observation failed for %s", tool_name, exc_info=True)

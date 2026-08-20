"""ADR 0031 D3 — ``ToolGovernanceMiddleware``, Phase 1 (observe-only).

``create_agent(..., middleware=self._build_agent_middleware())`` was already
wired at ``base.py``; the method returned an empty list. There is a wired,
empty middleware chain in front of every tool call on every agent, and unlike
the promotion-loop wrappers (``_risk_gated`` / ``_serialize_tool_result``)
middleware wraps the ``ToolNode`` — so it catches every tool regardless of how
that tool was registered. ``retrieve_workspace_context`` is the proof: it was
constructed directly and received neither wrapper.

**This middleware gates nothing.** It classifies and records:

- per-tool **latency**, which was measured and then discarded;
- per-tool **outcome** and its machine-readable **reason**;
- the value for ``DeepRunLog.status``, a column that existed and was never
  written.

**Phase 3 (D2) changed where the outcome comes from.** Phase 1 could only
recover "something failed" by matching the ``"Error: "`` prefix back off the
rendered string, because ``_serialize_tool_result`` flattened
``ToolResult(ok=False)`` into prose before any middleware could see it — which
collapsed every reason to ``INTERNAL``. The structured outcome now rides
``ToolMessage.artifact`` (LangChain's own out-of-band slot, "not sent to the
model"), so ``classify_tool_message`` reads what the tool reported instead of
guessing. The prefix check survives only as the last-resort signal for tools
that still hand-roll an error string.

The worked failure this makes visible: an LLM-provider outage produces
"reviewed; no confident fix" across every finding, every card stamped triaged,
and ``status="completed"`` at all four layers. The observations now carry
``outcome=failure`` with a real reason, and ``execute()`` no longer reports a
clean success over them (``tool_spec.resolve_run_outcome``).

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
    SUCCESS_ENVELOPE,
    TOOL_RESULT_ERROR_PREFIX,
    Failure,
    ToolCallObservation,
    ToolOutcome,
    ToolOutcomeEnvelope,
    ToolSpec,
    classify_exception,
    read_outcome_artifact,
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


def classify_tool_message(message: Any) -> ToolOutcomeEnvelope:
    """Classify a returned ``ToolMessage`` into a ``ToolOutcomeEnvelope``.

    Three signals, in strict precedence order. The first is the D2 fix; the
    other two are what Phase 1 had, kept as the fallback for the tools that do
    not yet return a ``ToolResult``.

    1. **The artifact** — ``ToolMessage.artifact`` carries the outcome the tool
       actually reported, put there by ``_serialize_tool_result``. This is the
       bit that used to be destroyed by flattening; it now survives, with its
       reason, so a "not found" stops being indistinguishable from a crash.
    2. **LangChain's ``ToolMessage.status``** — ``"error"`` when something in the
       tool pipeline caught an exception. Inferred, not reported, and the reason
       is genuinely unknown: ``INTERNAL``, the loud tier.
    3. **The ``"Error: "`` prefix** — last resort, for the ~49 tool bodies that
       hand-roll ``f"Error ...: {exc}"`` instead of returning a ``ToolResult``.
       Fitness function F4 is the ratchet that shrinks that population; until it
       is empty, this is the only signal those tools give us.
    """
    if not isinstance(message, ToolMessage):
        return SUCCESS_ENVELOPE

    carried = read_outcome_artifact(getattr(message, "artifact", None))
    if carried is not None:
        return carried

    if getattr(message, "status", None) == "error":
        return ToolOutcomeEnvelope(outcome=ToolOutcome.FAILURE, failure=Failure.INTERNAL, expected=False)

    content = getattr(message, "content", None)
    if isinstance(content, str) and content.lstrip().startswith(TOOL_RESULT_ERROR_PREFIX):
        return ToolOutcomeEnvelope(outcome=ToolOutcome.FAILURE, failure=Failure.INTERNAL, expected=False)

    return SUCCESS_ENVELOPE


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

    # ── tenancy (ADR 0031 D1) ─────────────────────────────────────────────

    def _strip_tenancy_args(self, request: ToolCallRequest, tool_name: str) -> ToolCallRequest:
        """Return *request* with every tenancy key removed from its arguments.

        The model does not get to name the tenant. ``agent.workspace_id`` is
        bound when the run is created from the authenticated request and is the
        only tenant a tool may act on, so an ``organization_id`` in the call's
        arguments is at best noise and at worst the cross-tenant escape hatch
        this phase exists to close.

        Stripping rather than refusing is deliberate. A refusal would surface to
        the model as a tool error it would retry, and the retry would be the
        same call — the model supplies the key because nine tool descriptions
        used to ask it to. Those descriptions are fixed in this same change;
        removing the value is what makes a stale one harmless.

        Never raises: ``request.override`` is immutable-by-design and a failure
        here must not take down a tool call that is about to be correctly
        scoped anyway.
        """
        from components.agents.application.policies.tool_tenancy import scrub_tenancy_keys

        try:
            tool_call = request.tool_call
            if not isinstance(tool_call, dict):
                return request
            args = tool_call.get("args")
            scrubbed, removed = scrub_tenancy_keys(args)
            if not removed:
                return request
            logger.warning(
                "agent_tool_tenancy_key_stripped tool=%s keys=%s agent_id=%s workspace_id=%s",
                tool_name,
                ",".join(sorted(set(removed))),
                getattr(self._agent, "agent_id", None),
                getattr(self._agent, "workspace_id", None),
            )
            return request.override(tool_call={**tool_call, "args": scrubbed})
        except Exception:  # pragma: no cover — the guard must not break the call
            logger.debug("tenancy arg strip failed for %s", tool_name, exc_info=True)
            return request

    # ── the seam ──────────────────────────────────────────────────────────

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        tool_call = request.tool_call if isinstance(request.tool_call, dict) else {}
        tool_name = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or "")

        # ADR 0031 D1 / Phase 3 — the tenant assertion. Middleware wraps the
        # ``ToolNode``, so this reaches every tool on every agent regardless of
        # how the tool was registered, which the promotion-loop wrappers cannot.
        request = self._strip_tenancy_args(request, tool_name)

        started = time.perf_counter()
        try:
            result = handler(request)
        except BaseException as exc:
            # Classify, record, and re-raise untouched. Letting an
            # implementation bug bubble is the documented contract for
            # ``wrap_tool_call`` ("handle runtime input errors; incorrect tool
            # implementation errors should bubble up"); D2 is a licence to
            # classify failures, never to swallow more of them. ``expected`` is
            # False because nothing declared this — we inferred it from the
            # exception type.
            self._record(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                envelope=ToolOutcomeEnvelope(
                    outcome=ToolOutcome.FAILURE,
                    failure=classify_exception(exc),
                    expected=False,
                ),
                latency_ms=self._elapsed_ms(started),
            )
            raise

        self._record(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            envelope=classify_tool_message(result),
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
        envelope: ToolOutcomeEnvelope,
        latency_ms: int,
    ) -> None:
        """Buffer the observation and log it. Never raises."""
        outcome = envelope.outcome
        failure = envelope.failure
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
                expected=envelope.expected,
                retriable=envelope.retriable,
            )
            self.buffer.record(observation)
            # Structured, grep-able, and free of tool input/output — the
            # payload already rides on the tool_observation row and duplicating
            # it here would put tool arguments into the log stream.
            log = logger.warning if observation.failed else logger.info
            log(
                "agent_tool_call tool=%s outcome=%s failure=%s expected=%s "
                "latency_ms=%s declared=%s agent_id=%s workspace_id=%s",
                tool_name,
                outcome,
                failure or "",
                envelope.expected,
                latency_ms,
                spec.is_declared,
                getattr(self._agent, "agent_id", None),
                getattr(self._agent, "workspace_id", None),
            )
        except Exception:  # pragma: no cover — observability never breaks a run
            logger.debug("tool governance observation failed for %s", tool_name, exc_info=True)

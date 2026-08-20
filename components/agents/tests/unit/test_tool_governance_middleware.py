"""ADR 0031 Phase 1 — ``ToolGovernanceMiddleware`` observes and enforces nothing.

Four things have to hold for Phase 1 to be the reversible, behaviour-preserving
change the ADR promises:

1. the middleware **fires** for a tool call and records latency + outcome;
2. it is **transparent** — the handler's return value is returned unchanged and
   a raised exception is re-raised unchanged, so no tool's behaviour moves;
3. an **undeclared** tool is observed exactly like a declared one, just labelled
   as undeclared — nothing is gated on the declaration;
4. the **failure classification** is right for both a success and a raised
   exception, including the ``ToolResult(ok=False)`` case whose ``ok`` bit
   ``_serialize_tool_result`` has already flattened into a string.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import ToolMessage

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.policies.tool_spec import (
    SUCCESS_ENVELOPE,
    Failure,
    Provenance,
    Scope,
    ToolOutcome,
    ToolOutcomeEnvelope,
    build_tool_spec,
)
from components.agents.infrastructure.adapters.langchain.middleware.tool_governance import (
    ToolGovernanceMiddleware,
    classify_tool_message,
)


class _StubAgent:
    """Minimal agent surface the middleware reads."""

    agent_id = "agent-1"
    workspace_id = "ws-1"

    _decorated_tools = [
        (
            "declared_tool",
            {
                "name": "declared_tool",
                "spec": build_tool_spec(
                    scope=Scope.WORKSPACE_BOUND,
                    risk=ToolRisk.READ,
                    provenance=Provenance.NONE,
                    failure_mode=Failure.UPSTREAM_UNAVAILABLE,
                    handles=("ai.code_security",),
                ),
            },
        ),
        (
            "undeclared_tool",
            {"name": "undeclared_tool", "spec": None},
        ),
    ]


def _request(tool_name: str, call_id: str = "call-1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": {}, "id": call_id},
        tool=None,
        state={},
        runtime=SimpleNamespace(),
    )


def _ok_message(content: str = "fine", call_id: str = "call-1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id)


@pytest.fixture
def middleware():
    return ToolGovernanceMiddleware(agent=_StubAgent())


class TestMiddlewareFires:
    def test_a_tool_call_is_observed(self, middleware):
        message = _ok_message()
        returned = middleware.wrap_tool_call(_request("declared_tool"), lambda _r: message)

        # Transparent: the handler's object comes straight back.
        assert returned is message

        observations = middleware.buffer.all()
        assert len(observations) == 1
        observed = observations[0]
        assert observed.tool_name == "declared_tool"
        assert observed.tool_call_id == "call-1"
        assert observed.outcome == ToolOutcome.SUCCESS
        assert observed.failure is None
        assert observed.declared is True
        assert observed.latency_ms >= 0

    def test_the_declaration_rides_along_on_the_observation(self, middleware):
        middleware.wrap_tool_call(_request("declared_tool"), lambda _r: _ok_message())
        payload = middleware.buffer.all()[0].as_payload()
        assert payload["scope"] == Scope.WORKSPACE_BOUND
        assert payload["handles"] == ["ai.code_security"]
        assert payload["declared"] is True
        assert "latency_ms" in payload

    def test_observations_are_retrievable_by_tool_call_id(self, middleware):
        middleware.wrap_tool_call(_request("declared_tool", "call-a"), lambda _r: _ok_message(call_id="call-a"))
        middleware.wrap_tool_call(_request("declared_tool", "call-b"), lambda _r: _ok_message(call_id="call-b"))
        assert middleware.buffer.get("call-a") is not middleware.buffer.get("call-b")
        assert middleware.buffer.get("nope") is None


class TestUndeclaredToolIsUnaffected:
    def test_an_undeclared_tool_still_runs_and_is_still_observed(self, middleware):
        message = _ok_message(content="undeclared result")
        returned = middleware.wrap_tool_call(_request("undeclared_tool"), lambda _r: message)

        assert returned is message
        observed = middleware.buffer.all()[0]
        assert observed.outcome == ToolOutcome.SUCCESS
        assert observed.declared is False
        # No declaration means no declaration fields — nothing invented.
        assert "scope" not in observed.as_payload()

    def test_a_tool_the_registry_has_never_heard_of_is_not_gated(self, middleware):
        message = _ok_message(content="mystery")
        returned = middleware.wrap_tool_call(_request("tool_from_nowhere"), lambda _r: message)
        assert returned is message
        assert middleware.buffer.all()[0].declared is False


class TestObserveOnlyEnforcesNothing:
    def test_a_raised_exception_is_re_raised_unchanged(self, middleware):
        boom = RuntimeError("implementation bug")

        def handler(_request):
            raise boom

        with pytest.raises(RuntimeError) as caught:
            middleware.wrap_tool_call(_request("declared_tool"), handler)
        assert caught.value is boom

    def test_the_middleware_never_substitutes_a_result(self, middleware):
        sentinel = _ok_message(content="the tool's own words")
        assert middleware.wrap_tool_call(_request("undeclared_tool"), lambda _r: sentinel) is sentinel

    def test_an_irreversible_declared_tool_is_still_allowed_through(self, middleware):
        """Risk is *recorded*, not enforced, in Phase 1. Enforcement stays where
        it already lives — ``_risk_gated`` in the promotion loop. If this test
        ever fails, observe-only has quietly become enforce."""
        agent = _StubAgent()
        agent._decorated_tools = [
            (
                "dangerous",
                {"name": "dangerous", "spec": build_tool_spec(risk=ToolRisk.IRREVERSIBLE)},
            )
        ]
        mw = ToolGovernanceMiddleware(agent=agent)
        message = _ok_message(content="did the dangerous thing")
        assert mw.wrap_tool_call(_request("dangerous"), lambda _r: message) is message


class TestFailureClassification:
    """Three signals, in precedence order — see ``classify_tool_message``."""

    def test_success_message_classifies_as_success(self):
        envelope = classify_tool_message(_ok_message())
        assert (envelope.outcome, envelope.failure) == (ToolOutcome.SUCCESS, None)

    def test_the_carried_artifact_wins_over_every_other_signal(self):
        """ADR 0031 D2 — the outcome the tool reported, carried out-of-band.

        The content here says ``"Error: ..."`` (which the prefix fallback would
        read as ``INTERNAL``) while the artifact says ``NOT_FOUND``. The
        artifact must win, or D2 has bought nothing over Phase 1.
        """
        envelope = ToolOutcomeEnvelope(
            outcome=ToolOutcome.FAILURE,
            failure=Failure.NOT_FOUND,
            expected=True,
        )
        message = ToolMessage(
            content="Error: no such finding",
            tool_call_id="c",
            artifact=envelope.as_artifact(),
        )
        classified = classify_tool_message(message)
        assert classified.failure == Failure.NOT_FOUND
        assert classified.expected is True

    def test_a_success_artifact_is_believed_over_a_misleading_prefix(self):
        """The inverse, which is the real risk of a prefix heuristic: a tool
        whose legitimate output happens to begin with ``"Error:"`` (a log line,
        a grep result) was previously misreported as a failure."""
        message = ToolMessage(
            content="Error: NullPointerException at Foo.java:12 — 3 occurrences",
            tool_call_id="c",
            artifact=SUCCESS_ENVELOPE.as_artifact(),
        )
        assert classify_tool_message(message).outcome == ToolOutcome.SUCCESS

    def test_a_foreign_artifact_is_ignored_rather_than_misread(self):
        message = ToolMessage(content="fine", tool_call_id="c", artifact={"document_id": "doc_123"})
        assert classify_tool_message(message).outcome == ToolOutcome.SUCCESS

    def test_langchain_error_status_classifies_as_failure(self):
        message = ToolMessage(content="blew up", tool_call_id="c", status="error")
        classified = classify_tool_message(message)
        assert (classified.outcome, classified.failure) == (ToolOutcome.FAILURE, Failure.INTERNAL)
        assert classified.expected is False, "nothing declared this — it was inferred"

    def test_the_prefix_fallback_still_applies_when_no_artifact_is_carried(self):
        """A tool that carries no outcome falls through to the prefix check.

        ``INTERNAL`` + ``expected=False`` is the honest reading: something
        failed and we do not know what.
        """
        message = ToolMessage(content="Error: something went wrong", tool_call_id="c")
        classified = classify_tool_message(message)
        assert classified.outcome == ToolOutcome.FAILURE
        assert classified.failure == Failure.INTERNAL
        assert classified.expected is False

    def test_the_prefix_fallback_does_not_reach_the_hand_rolled_house_style(self):
        """Measured, not assumed — and the reason F4 matters more than it looked.

        The ~49 tools that swallow into a string do not write ``"Error: ..."``.
        Every one of them writes ``f"Error <verb>ing X: {exc}"`` — no colon after
        "Error". So the Phase 1 prefix heuristic, which reads as though it
        covered the hand-rolled population, in fact only ever matched
        ``ToolResult.serialize()`` output. **Those failures were invisible then
        and are invisible now**; the only fix is converting the bodies, which is
        exactly what F4 (``tests/architecture/test_tool_blanket_exception.py``)
        ratchets toward.

        This test pins the gap so it stays a known, stated limitation rather
        than a comfortable assumption. When the bodies are converted it can go.
        """
        message = ToolMessage(content="Error listing tasks: boom", tool_call_id="c")
        assert classify_tool_message(message).outcome == ToolOutcome.SUCCESS, (
            "if this now classifies as a failure the prefix heuristic was broadened — "
            "check that it does not also flag legitimate output that merely mentions an error"
        )

    def test_a_successful_tool_result_is_not_misread_as_a_failure(self):
        from components.agents.infrastructure.adapters.langchain.base import ToolResult

        message = ToolMessage(content=ToolResult(ok=True, message="12 findings").serialize(), tool_call_id="c")
        classified = classify_tool_message(message)
        assert (classified.outcome, classified.failure) == (ToolOutcome.SUCCESS, None)

    def test_a_raised_exception_is_classified_before_it_propagates(self, middleware):
        def handler(_request):
            raise ConnectionError("provider down")

        with pytest.raises(ConnectionError):
            middleware.wrap_tool_call(_request("declared_tool"), handler)

        observed = middleware.buffer.all()[0]
        assert observed.outcome == ToolOutcome.FAILURE
        assert observed.failure == Failure.UPSTREAM_UNAVAILABLE


class TestBufferSummary:
    def test_summary_counts_calls_failures_and_latency(self, middleware):
        middleware.wrap_tool_call(_request("declared_tool", "a"), lambda _r: _ok_message(call_id="a"))
        middleware.wrap_tool_call(
            _request("undeclared_tool", "b"),
            lambda _r: ToolMessage(content="nope", tool_call_id="b", status="error"),
        )
        summary = middleware.buffer.summary()
        assert summary["calls"] == 2
        assert summary["failed"] == 1
        assert summary["undeclared"] == 1
        assert summary["failed_tools"] == ["undeclared_tool"]
        assert summary["failures_by_reason"] == {Failure.INTERNAL: 1}

    def test_empty_buffer_summarises_to_nothing(self, middleware):
        assert middleware.buffer.summary() == {}

    def test_clear_resets_the_turn(self, middleware):
        middleware.wrap_tool_call(_request("declared_tool"), lambda _r: _ok_message())
        middleware.buffer.clear()
        assert middleware.buffer.all() == []
        assert middleware.buffer.get("call-1") is None

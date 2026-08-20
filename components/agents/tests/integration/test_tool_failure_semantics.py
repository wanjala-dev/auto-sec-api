"""ADR 0031 D2 (Phase 3) — a tool's outcome survives serialization, and the run says so.

Three sound mechanisms existed before this change and none was connected to the
other two:

1. ``ToolResult.ok`` — flattened to a string by ``_serialize_tool_result``
   *before* anything could read it, so Phase 1's middleware could only recover
   "something failed" from the ``"Error: "`` prefix and collapsed every reason
   to ``INTERNAL``;
2. ``DeepRunLog.status`` — written by Phase 1, but with that impoverished
   classification;
3. ``execute()`` — ``success=True`` and ``status="completed"``, unconditionally.

The reproduction at the top of this file is the defect: a turn whose only tool
call failed reported a clean success at every layer. The rest of the file is the
fix — the ``ok`` bit and a machine-readable reason ride ``ToolMessage.artifact``,
which LangChain documents as "additional data not sent to the model but can be
accessed programmatically", so the bytes the model reads do not move.

``TestTheModelVisibleBytesDidNotMove`` is the load-bearing test: this repo has
already been bitten by a tool-definition byte change (ADR 0031 Phase 2 had to
restate an inferred ``args_schema`` exactly, title included). The outcome travels
out-of-band precisely so that class of regression cannot happen here.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.policies.tool_spec import (
    Failure,
    Provenance,
    RunOutcome,
    Scope,
    ToolOutcome,
    read_outcome_artifact,
    resolve_run_outcome,
)
from components.agents.infrastructure.adapters.langchain.base import (
    EXECUTION_STATUS_COMPLETED,
    EXECUTION_STATUS_FAILED,
    EXECUTION_STATUS_PARTIAL,
    BaseAgent,
    ToolResult,
)
from components.agents.infrastructure.adapters.langchain.base import tool as tool_decorator


class _ScriptedToolCallingModel(GenericFakeChatModel):
    """A fake chat model that supports ``bind_tools`` (see Phase 2's suite)."""

    def bind_tools(self, tools, **kwargs):
        return self


class _FailureAgent(BaseAgent):
    """Four tools, one per outcome shape D2 has to tell apart.

    Deliberately not ``@register_agent``-ed — this exercises the framework seam
    without adding a row the capability-inventory tests would have to account for.
    """

    #: Set per-test; each tool reads its instruction from here so one class
    #: covers every case without a subclass explosion.
    behaviour: str = "ok"

    @tool_decorator(
        name="probe_tool",
        description="A probe tool.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.UPSTREAM_UNAVAILABLE,
    )
    def probe_tool(self, input_str: str = "") -> ToolResult | str:
        if self.behaviour == "raise":
            raise ConnectionError("provider down")
        if self.behaviour == "not_found":
            return ToolResult(ok=False, error="no such finding", failure=Failure.NOT_FOUND)
        if self.behaviour == "undeclared_failure":
            # ``ok=False`` with no reason — the declaration is what names it.
            return ToolResult(ok=False, error="upstream said no")
        if self.behaviour == "plain_string":
            return "just a string"
        return ToolResult(ok=True, message="12 findings")

    @tool_decorator(
        name="second_tool",
        description="A second probe tool.",
        scope=Scope.WORKSPACE_BOUND,
        risk=ToolRisk.READ,
        provenance=Provenance.NONE,
        failure_mode=Failure.INTERNAL,
    )
    def second_tool(self, input_str: str = "") -> ToolResult:
        return ToolResult(ok=True, message="second ok")


def _make_agent(agent_cls=_FailureAgent, *, model=None):
    """A real agent, with its real executor and real middleware chain."""
    from components.agents.infrastructure.adapters.langchain import base as base_module

    fake_memory_service = MagicMock(name="fake_memory_service")
    fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
    fake_memory_service.get_conversation_id = MagicMock(return_value=None)

    fake_provider = MagicMock(name="fake_llm_provider")
    fake_provider.get_llm = MagicMock(return_value=model if model is not None else MagicMock())

    with patch.object(base_module, "get_agent_memory_service", return_value=fake_memory_service):
        return agent_cls(
            agent_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            workspace_id=str(uuid.uuid4()),
            llm_provider=fake_provider,
        )


def _model_calling(*tool_calls: tuple[str, str]) -> _ScriptedToolCallingModel:
    """A model that makes the given tool calls, then answers."""
    return _ScriptedToolCallingModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": name, "args": {"input_str": "x"}, "id": call_id} for name, call_id in tool_calls
                    ],
                ),
                # The narration an LLM produces regardless of whether the tools
                # worked — the thing that made the defect invisible.
                AIMessage(content="Handled it: reviewed; no confident fix."),
            ]
        )
    )


def _run(behaviour: str, *tool_calls: tuple[str, str]) -> tuple[_FailureAgent, dict]:
    agent = _make_agent(model=_model_calling(*(tool_calls or (("probe_tool", "call-1"),))))
    agent.behaviour = behaviour
    return agent, agent.execute("do the thing")


# ─────────────────────────────────────────────────────────────────────────────
# The defect, stated as the behaviour that must no longer hold
# ─────────────────────────────────────────────────────────────────────────────


class TestTheSilentSuccessIsGone:
    """Before D2 every one of these reported a clean success."""

    def test_a_turn_whose_only_tool_call_failed_does_not_report_success(self):
        agent, result = _run("not_found")

        assert result["success"] is False, (
            "the run reported success over a failed tool call — this is the silent-success "
            "class ADR 0031 D2 exists to remove"
        )
        assert result["status"] == RunOutcome.FAILED
        # The narration is still returned. Nothing is lost; it just stops being
        # labelled a success.
        assert result["result"] == "Handled it: reviewed; no confident fix."
        assert "probe_tool" in result["error"]

    def test_the_execution_row_records_the_same_verdict(self):
        agent, _ = _run("not_found")
        kwargs = agent.memory_service.record_execution.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["status"] == EXECUTION_STATUS_FAILED
        assert "probe_tool" in kwargs["error_message"]

    def test_a_mixed_turn_is_partial_not_completed(self):
        """One tool failed, one succeeded. The answer is usable, so ``success``
        stays True — but ``completed`` would be a lie, and ``failed`` would throw
        away a real answer. ``partial`` is the honest third state."""
        agent = _make_agent(model=_model_calling(("probe_tool", "c1"), ("second_tool", "c2")))
        agent.behaviour = "not_found"
        result = agent.execute("do two things")

        assert result["status"] == RunOutcome.PARTIAL
        assert result["success"] is True
        kwargs = agent.memory_service.record_execution.call_args.kwargs
        assert kwargs["status"] == EXECUTION_STATUS_PARTIAL

    def test_a_clean_turn_is_still_completed(self):
        """The regression guard: 100 tools declare nothing and the overwhelming
        majority of turns succeed. None of them may move."""
        agent, result = _run("ok")
        assert result["success"] is True
        assert result["status"] == RunOutcome.COMPLETED
        kwargs = agent.memory_service.record_execution.call_args.kwargs
        assert kwargs["status"] == EXECUTION_STATUS_COMPLETED
        assert kwargs["success"] is True

    def test_a_turn_with_no_tool_calls_at_all_is_completed(self):
        agent = _make_agent(model=_ScriptedToolCallingModel(messages=iter([AIMessage(content="no tools needed")])))
        result = agent.execute("just chat")
        assert result["success"] is True
        assert result["status"] == RunOutcome.COMPLETED


# ─────────────────────────────────────────────────────────────────────────────
# Classification — the reason survives, and it is not INTERNAL for everything
# ─────────────────────────────────────────────────────────────────────────────


class TestTheOutcomeSurvivesSerialization:
    def test_a_declared_failure_reason_reaches_the_middleware(self):
        agent, _ = _run("not_found")
        observed = agent._tool_call_observations.all()[0]
        assert observed.outcome == ToolOutcome.FAILURE
        assert observed.failure == Failure.NOT_FOUND, (
            "the reason was flattened away again — before D2 every failure collapsed to INTERNAL"
        )
        assert observed.expected is True, "a ToolResult(ok=False) is a failure the tool reported, not one we inferred"

    def test_an_unnamed_failure_falls_back_to_the_tools_declared_failure_mode(self):
        """D2: *the tool declares its failure semantics, and the framework
        classifies the outcome.* ``probe_tool`` declares
        ``failure_mode=UPSTREAM_UNAVAILABLE``, so an ``ok=False`` that names no
        reason is classified as that rather than as ``INTERNAL``."""
        agent, _ = _run("undeclared_failure")
        observed = agent._tool_call_observations.all()[0]
        assert observed.failure == Failure.UPSTREAM_UNAVAILABLE
        assert observed.expected is True

    def test_a_raised_exception_is_internal_and_loud(self):
        """LangChain's own guidance: handle runtime input errors, let
        implementation bugs bubble. The exception still propagates; the run
        fails; the classification is not dressed up as an expected outcome."""
        agent, result = _run("raise")

        assert result["success"] is False
        observed = agent._tool_call_observations.all()[0]
        assert observed.outcome == ToolOutcome.FAILURE
        assert observed.failure == Failure.UPSTREAM_UNAVAILABLE  # ConnectionError
        assert observed.expected is False, "an escaped exception is inferred, never a declared outcome"

    def test_a_successful_tool_result_is_observed_as_success(self):
        agent, _ = _run("ok")
        observed = agent._tool_call_observations.all()[0]
        assert observed.outcome == ToolOutcome.SUCCESS
        assert observed.failure is None

    def test_a_plain_string_return_is_still_a_success(self):
        """Most tools return a bare string. They carry no outcome, so no
        artifact is attached and the middleware's last-resort signals apply —
        the framework does not assert a success it was never told about."""
        agent, _ = _run("plain_string")
        observed = agent._tool_call_observations.all()[0]
        assert observed.outcome == ToolOutcome.SUCCESS


# ─────────────────────────────────────────────────────────────────────────────
# The constraint that matters most
# ─────────────────────────────────────────────────────────────────────────────


class TestTheModelVisibleBytesDidNotMove:
    """The serialized tool result is bytes the model reads.

    Both halves are pinned: the tool *definition* the model is offered, and the
    tool *result* it reads back.
    """

    def _tool_message(self, behaviour: str) -> ToolMessage:
        agent, _ = _run(behaviour)
        promoted = next(t for t in agent.tools if t.name == "probe_tool")
        message = promoted.invoke({"args": {"input_str": "x"}, "id": "c", "name": "probe_tool", "type": "tool_call"})
        return message

    @pytest.mark.parametrize(
        "behaviour,expected",
        [
            ("ok", "12 findings"),
            ("not_found", "Error: no such finding"),
            ("undeclared_failure", "Error: upstream said no"),
            ("plain_string", "just a string"),
        ],
    )
    def test_the_content_the_model_reads_is_byte_identical(self, behaviour, expected):
        message = self._tool_message(behaviour)
        assert message.content == expected

    def test_the_content_is_exactly_what_tool_result_serialize_renders(self):
        """Stated against the renderer rather than a literal, so a future change
        to ``serialize()`` cannot pass this test by moving both sides at once —
        the literals above are the second, independent anchor."""
        assert self._tool_message("not_found").content == ToolResult(ok=False, error="no such finding").serialize()

    def test_the_outcome_travels_out_of_band_not_in_the_content(self):
        message = self._tool_message("not_found")
        envelope = read_outcome_artifact(message.artifact)
        assert envelope is not None
        assert envelope.outcome == ToolOutcome.FAILURE
        assert envelope.failure == Failure.NOT_FOUND
        # And none of it leaked into what the model sees.
        assert "not_found" not in message.content
        assert message.status == "success", (
            "ToolMessage.status is provider-visible (Anthropic renders it as is_error); "
            "D2 must not move it as a side effect of classifying"
        )

    def test_the_artifact_is_invisible_in_the_provider_payload(self):
        """The claim the whole design rests on, asserted against LangChain rather
        than against our reading of its docs."""
        from langchain_core.messages import convert_to_openai_messages

        carrying = self._tool_message("not_found")
        bare = ToolMessage(
            content=carrying.content,
            tool_call_id=carrying.tool_call_id,
            name=carrying.name,
        )
        assert convert_to_openai_messages([carrying]) == convert_to_openai_messages([bare])

    def test_the_tool_definition_offered_to_the_model_is_unchanged(self):
        """``response_format="content_and_artifact"`` is a tool-side field. If it
        ever started showing up in the function schema, the model's view of the
        tool would have changed."""
        from langchain_core.utils.function_calling import convert_to_openai_tool

        agent = _make_agent()
        promoted = next(t for t in agent.tools if t.name == "probe_tool")

        def _probe(input_str: str = "") -> str:  # the pre-D2 shape
            return ""

        before = StructuredTool.from_function(
            func=_probe,
            name=promoted.name,
            description=promoted.description,
            args_schema=promoted.args_schema,
        )
        assert convert_to_openai_tool(promoted) == convert_to_openai_tool(before)


# ─────────────────────────────────────────────────────────────────────────────
# The run-outcome policy, on its own
# ─────────────────────────────────────────────────────────────────────────────


class TestRunOutcomePolicy:
    @pytest.mark.parametrize(
        "total,failed,expected",
        [
            (0, 0, RunOutcome.COMPLETED),
            (3, 0, RunOutcome.COMPLETED),
            (3, 1, RunOutcome.PARTIAL),
            (3, 3, RunOutcome.FAILED),
            (1, 1, RunOutcome.FAILED),
        ],
    )
    def test_the_three_states(self, total, failed, expected):
        assert resolve_run_outcome(total_calls=total, failed_calls=failed) == expected

    def test_it_is_framework_free(self):
        """The policy lives in the application layer; the architecture tests
        forbid Django/LangChain there, and this states why it matters."""
        import components.agents.application.policies.tool_spec as module

        source = open(module.__file__, encoding="utf-8").read()
        assert "import django" not in source
        assert "from langchain" not in source


# ─────────────────────────────────────────────────────────────────────────────
# The four layers, against a real DeepRun
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTheFourLayersAgree:
    def _run_against_a_deep_run(self, behaviour, workspace_factory, user_factory):
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = DeepRun.objects.create(
            thread_id=f"thread-d2-{behaviour}",
            plan_id=f"plan-d2-{behaviour}",
            user=user_factory(),
            workspace=workspace_factory(),
            status=DeepRun.STATUS_RUNNING,
        )
        agent = _make_agent(model=_model_calling(("probe_tool", "call-1")))
        agent.behaviour = behaviour
        result = agent.execute("do it", context={"run_context": {"run_id": run.thread_id}})
        return run, agent, result

    def test_a_failed_tool_call_is_failed_at_every_layer(self, workspace_factory, user_factory):
        run, _agent, result = self._run_against_a_deep_run("not_found", workspace_factory, user_factory)

        # Layer 1 — the per-tool observation row.
        observation = run.logs.filter(event_type="tool_observation", tool_name="probe_tool").first()
        assert observation is not None
        assert observation.status == ToolOutcome.FAILURE
        governance = observation.payload["governance"]
        assert governance["failure"] == Failure.NOT_FOUND
        assert governance["expected"] is True

        # Layer 2 — the run payload / AgentExecution row.
        assert result["success"] is False
        assert result["status"] == RunOutcome.FAILED

        # Layer 3 — the run_telemetry row.
        telemetry = run.logs.filter(event_type="run_telemetry").first()
        assert telemetry is not None
        assert telemetry.status == RunOutcome.FAILED

    def test_a_partial_execution_is_terminal_for_the_celery_idempotency_guard(self, workspace_factory, user_factory):
        """A consequence of adding a third state, caught by looking for it.

        ``run_agent_execution`` skips a redelivered task whose row is already
        terminal, because ``agent.execute()`` is an expensive, non-idempotent
        LLM call. It tested only for ``completed``. A turn that is now
        ``partial`` would have been ``completed`` before D2 — so without adding
        it here, introducing the state would have quietly made those turns
        replayable on a worker crash and double-spent the tokens.
        """
        from infrastructure.persistence.ai.agents.models import Agent, AgentExecution

        user = user_factory()
        workspace = workspace_factory(owner=user)
        agent_row = Agent.objects.create(
            agent_type="triage_agent",
            user=user,
            workspace=workspace,
            status="active",
            config={},
        )
        execution = AgentExecution.objects.create(
            agent=agent_row,
            query="q",
            result="an answer, over some failed tool calls",
            status=AgentExecution.STATUS_PARTIAL,
            success=True,
            progress=100,
        )

        from components.agents.infrastructure.tasks.agent_tasks import run_agent_execution

        result = run_agent_execution.apply(kwargs={"execution_id": str(execution.id)}).get()
        assert result["skipped"] == "already_completed", (
            "a partial execution was re-run — it is terminal, and replaying it double-spends an LLM call"
        )

    def test_a_clean_tool_call_stays_success_at_every_layer(self, workspace_factory, user_factory):
        run, _agent, result = self._run_against_a_deep_run("ok", workspace_factory, user_factory)

        observation = run.logs.filter(event_type="tool_observation", tool_name="probe_tool").first()
        assert observation.status == ToolOutcome.SUCCESS
        assert result["success"] is True
        telemetry = run.logs.filter(event_type="run_telemetry").first()
        assert telemetry.status == "success"

"""ADR 0031 Phase 2 — ``retrieve_workspace_context`` is the reference conversion.

The tool used to be built directly with ``StructuredTool.from_function`` inside
``_setup_tools``, so it never entered the ``for`` loop over
``_decorated_tools`` where ``_risk_gated`` and ``_serialize_tool_result`` are
applied. It is the single tool every agent has, and it was the one tool the
promotion-time wrappers could not reach — the concrete instance of the D4
bypass.

This test proves three things about the conversion:

1. **The tool is declared and promoted** — it carries a complete ``ToolSpec``
   and reaches ``agent.tools`` through the one registration path, for every
   agent in the fleet.
2. **The middleware actually fires for it**, through the real ``create_agent``
   graph and the real ``ToolNode`` — not a hand-called wrapper. This is the
   claim the whole of D3 rests on, so it is tested against the framework
   rather than against our own plumbing.
3. **The model-facing schema did not move.** Supplying an explicit
   ``args_schema`` (the promotion loop always passes one) has to reproduce
   exactly what ``from_function`` used to infer, or the bytes in the tool
   definition sent to the LLM change and the conversion is not behaviour-
   preserving.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from components.agents.application.policies.tool_risk import ToolRisk
from components.agents.application.policies.tool_spec import (
    Failure,
    Provenance,
    Scope,
    ToolOutcome,
    ToolSpec,
)
from components.agents.infrastructure.adapters.langchain.base import (
    BaseAgent,
    WorkspaceRetrievalMixin,
)

TOOL_NAME = "retrieve_workspace_context"


class _ProbeAgent(BaseAgent):
    """A bare ``BaseAgent`` subclass — no tools of its own.

    Deliberately not ``@register_agent``-ed: this exercises the framework seam
    without adding a row to the agent registry that the capability-inventory
    tests would then have to account for. Its only declared tool is the one
    inherited from ``WorkspaceRetrievalMixin``, which is precisely the tool
    under test.
    """


class _ScriptedToolCallingModel(GenericFakeChatModel):
    """A fake chat model that supports ``bind_tools``.

    ``create_agent`` binds the tools to the model; ``BaseChatModel.bind_tools``
    raises by default. Returning ``self`` is enough — the scripted messages
    already carry the tool calls we want made.
    """

    def bind_tools(self, tools, **kwargs):
        return self


def _make_agent(*, model=None) -> _ProbeAgent:
    """Build a real ``_ProbeAgent``, including its real executor + middleware.

    Mirrors ``AgentTestCase.make_agent`` except that it deliberately does NOT
    stub ``_create_agent_executor`` — the executor and its middleware chain are
    what this test exists to exercise.
    """
    from components.agents.infrastructure.adapters.langchain import base as base_module

    fake_memory_service = MagicMock(name="fake_memory_service")
    fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
    fake_memory_service.get_conversation_id = MagicMock(return_value=None)

    fake_provider = MagicMock(name="fake_llm_provider")
    fake_provider.get_llm = MagicMock(return_value=model if model is not None else MagicMock())

    with patch.object(
        base_module,
        "get_agent_memory_service",
        return_value=fake_memory_service,
    ):
        return _ProbeAgent(
            agent_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            workspace_id=str(uuid.uuid4()),
            llm_provider=fake_provider,
        )


class TestRetrievalToolIsDeclaredAndPromoted:
    def test_the_tool_carries_a_complete_declaration(self):
        spec = WorkspaceRetrievalMixin.retrieve_workspace_context._agent_tool_meta["spec"]
        assert isinstance(spec, ToolSpec)
        assert spec.is_complete is True
        assert spec.scope == Scope.WORKSPACE_BOUND
        assert spec.risk == ToolRisk.READ
        assert spec.provenance == Provenance.NONE
        assert spec.failure_mode == Failure.UPSTREAM_UNAVAILABLE

    def test_the_declared_risk_matches_what_the_gate_already_resolved(self):
        """The declaration must not *move* the gate. Before the conversion the
        tool had no entry in ``_TOOL_RISK`` and no ``risk=``, so it resolved to
        ``read``; declaring ``read`` explicitly changes nothing."""
        from components.agents.application.policies.tool_risk import resolve_tool_risk

        spec = WorkspaceRetrievalMixin.retrieve_workspace_context._agent_tool_meta["spec"]
        assert resolve_tool_risk(TOOL_NAME, spec.risk) == resolve_tool_risk(TOOL_NAME, None)

    def test_it_reaches_the_agent_through_the_promotion_loop(self):
        agent = _make_agent()
        names = [t.name for t in agent.tools]
        assert TOOL_NAME in names
        # The promotion loop appends declared tools in MRO order and the mixin
        # sits last, which is the position the old unconditional append gave
        # it. Ordering is what the model reads, so it is pinned.
        assert names[-1] == TOOL_NAME

    def test_every_registered_agent_declares_it(self):
        """One conversion, whole fleet — the reason this tool was chosen first.

        ``ai_teammate`` is the documented exception: it overrides
        ``_setup_tools`` to hold zero tools because its workers are agents, not
        tools.
        """
        from components.agents.infrastructure.adapters.langchain.agents import discover_agents
        from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

        discover_agents()
        missing = []
        for name in AgentRegistry.list_agents():
            agent_cls = AgentRegistry.get_agent_class(name)
            if agent_cls is None:
                continue
            declared = {(meta.get("name") or method) for method, meta in agent_cls._decorated_tools}
            if TOOL_NAME not in declared:
                missing.append(name)
        assert missing == [], f"agents missing the universal retrieval declaration: {missing}"


class TestSchemaIsUnchangedByTheConversion:
    def test_retrieval_tool_schema_is_unchanged_by_conversion(self):
        """The pre-conversion schema, reproduced from the original construction.

        ``StructuredTool.from_function(func=_retrieve, name=..., description=...)``
        with ``def _retrieve(query: str) -> str`` inferred this exact JSON
        schema. If the explicit ``args_schema`` drifts from it, the tool
        definition the model receives changes and "behaviour preserving" stops
        being true.
        """

        def _retrieve(query: str) -> str:  # the original signature, verbatim
            return ""

        meta = WorkspaceRetrievalMixin.retrieve_workspace_context._agent_tool_meta
        before = StructuredTool.from_function(
            func=_retrieve,
            name=meta["name"],
            description=meta["description"],
        )
        after = _make_agent().tools[-1]

        assert after.name == before.name
        assert after.description == before.description
        assert after.args_schema.model_json_schema() == before.args_schema.model_json_schema()
        assert after.tool_call_schema.model_json_schema() == before.tool_call_schema.model_json_schema()


class TestMiddlewareFiresForTheConvertedTool:
    """The D3 claim, tested against the real graph rather than our plumbing."""

    def _run_one_tool_call(self, agent, *, tool_returns: str):
        # Swap the promoted tool's body so the run is deterministic and never
        # touches pgvector. The promotion wrappers and the middleware are
        # untouched — they are what is under test.
        promoted = next(t for t in agent.tools if t.name == TOOL_NAME)
        promoted.func = lambda query="", **_kw: tool_returns
        agent._create_agent_executor()
        return agent.agent_executor.invoke({"input": "what is this workspace"})

    def _agent_with_script(self, tool_returns: str):
        model = _ScriptedToolCallingModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": TOOL_NAME, "args": {"query": "mission"}, "id": "call-1"},
                        ],
                    ),
                    AIMessage(content="Here is what I found."),
                ]
            )
        )
        agent = _make_agent(model=model)
        return agent

    def test_the_middleware_observes_a_successful_retrieval(self):
        agent = self._agent_with_script("chunks")
        result = self._run_one_tool_call(agent, tool_returns="[1] (mission)\nWe do security.")

        assert result["output"] == "Here is what I found."

        observations = agent._tool_call_observations.all()
        assert [o.tool_name for o in observations] == [TOOL_NAME], observations
        observed = observations[0]
        assert observed.outcome == ToolOutcome.SUCCESS
        assert observed.declared is True
        assert observed.tool_call_id == "call-1"
        assert observed.latency_ms >= 0
        # The declaration reached the observation, which is what makes the
        # recorded data useful rather than just present.
        assert observed.as_payload()["scope"] == Scope.WORKSPACE_BOUND

    def test_the_middleware_classifies_a_failed_retrieval(self):
        """A ``ToolResult(ok=False)`` is flattened to ``"Error: ..."`` by
        ``_serialize_tool_result`` before anything downstream can read the
        ``ok`` bit. The middleware recovers it — this is the observation that
        makes an LLM/provider outage visible instead of silent."""
        from components.agents.infrastructure.adapters.langchain.base import ToolResult

        agent = self._agent_with_script("failure")
        rendered = ToolResult(ok=False, error="retrieval backend unavailable").serialize()
        self._run_one_tool_call(agent, tool_returns=rendered)

        observed = agent._tool_call_observations.all()[0]
        assert observed.outcome == ToolOutcome.FAILURE
        assert observed.failure == Failure.INTERNAL

    def test_a_failing_turn_still_reports_success_but_says_so_loudly(self, caplog):
        """Observe-only: Phase 1 changes no status. It only stops the
        contradiction being invisible. When D2 lands in Phase 3 this warning
        becomes a real failed status and this assertion changes with it."""
        import logging

        from components.agents.infrastructure.adapters.langchain.base import ToolResult

        agent = self._agent_with_script("failure")
        rendered = ToolResult(ok=False, error="provider 503").serialize()
        self._run_one_tool_call(agent, tool_returns=rendered)

        with caplog.at_level(logging.WARNING):
            agent._warn_on_success_over_tool_failures()

        assert any("agent_run_reported_success_with_tool_failures" in r.message for r in caplog.records)

    def test_run_state_carries_the_tool_outcome_summary(self):
        agent = self._agent_with_script("ok")
        self._run_one_tool_call(agent, tool_returns="fine")
        summary = agent._tool_outcome_summary()
        assert summary["calls"] == 1
        assert summary["failed"] == 0
        assert summary["undeclared"] == 0


class TestUndeclaredToolsAreUnaffected:
    def test_an_undeclared_tool_runs_and_returns_exactly_what_it_returned_before(self):
        """The bar for Phase 1: 100 tools declare nothing and none of them may
        change. Exercised through the same real graph as the converted tool."""
        from components.agents.infrastructure.adapters.langchain.base import tool as tool_decorator

        class _UndeclaredToolAgent(BaseAgent):
            @tool_decorator(name="plain_reader", description="reads a thing")
            def plain_reader(self, input_str: str = "") -> str:
                return f"plain result for {input_str!r}"

        model = _ScriptedToolCallingModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "plain_reader", "args": {"input_str": "x"}, "id": "c1"}],
                    ),
                    AIMessage(content="done"),
                ]
            )
        )
        from components.agents.infrastructure.adapters.langchain import base as base_module

        fake_memory_service = MagicMock()
        fake_memory_service.get_memory = MagicMock(return_value=MagicMock())
        fake_memory_service.get_conversation_id = MagicMock(return_value=None)
        fake_provider = MagicMock()
        fake_provider.get_llm = MagicMock(return_value=model)
        with patch.object(base_module, "get_agent_memory_service", return_value=fake_memory_service):
            agent = _UndeclaredToolAgent(
                agent_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                workspace_id=str(uuid.uuid4()),
                llm_provider=fake_provider,
            )

        declared_meta = dict(_UndeclaredToolAgent._decorated_tools)["plain_reader"]
        assert declared_meta["spec"].is_declared is False

        result = agent.agent_executor.invoke({"input": "go"})
        assert result["output"] == "done"

        # The tool ran, unchanged, and was observed as undeclared — nothing
        # about it was gated on the missing declaration.
        observations = agent._tool_call_observations.all()
        assert len(observations) == 1
        assert observations[0].tool_name == "plain_reader"
        assert observations[0].declared is False
        assert observations[0].outcome == ToolOutcome.SUCCESS

        # And the tool's own output reached the model verbatim.
        steps = list(result["intermediate_steps"])
        assert steps[0][1] == "plain result for 'x'"


@pytest.mark.django_db
class TestDeepRunLogStatusIsWritten:
    """``DeepRunLog.status`` has existed since the model was written and was
    never passed. Phase 1 writes it, on the row that already exists."""

    def test_tool_observation_row_carries_status_and_latency(self, workspace_factory, user_factory):
        from infrastructure.persistence.ai.agents.models import DeepRun

        workspace = workspace_factory()
        user = user_factory()
        run = DeepRun.objects.create(
            thread_id="thread-governance",
            plan_id="plan-governance",
            user=user,
            workspace=workspace,
            status=DeepRun.STATUS_RUNNING,
        )

        model = _ScriptedToolCallingModel(
            messages=iter(
                [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": TOOL_NAME, "args": {"query": "q"}, "id": "call-9"}],
                    ),
                    AIMessage(content="answered"),
                ]
            )
        )
        agent = _make_agent(model=model)
        promoted = next(t for t in agent.tools if t.name == TOOL_NAME)
        promoted.func = lambda query="", **_kw: "[1] (mission)\nsome context"
        agent._create_agent_executor()

        result = agent.agent_executor.invoke({"input": "q"})
        agent._persist_tool_observations({"run_id": run.thread_id}, result["intermediate_steps"])

        row = run.logs.filter(event_type="tool_observation", tool_name=TOOL_NAME).first()
        assert row is not None
        assert row.status == ToolOutcome.SUCCESS
        governance = row.payload["governance"]
        assert governance["outcome"] == ToolOutcome.SUCCESS
        assert governance["declared"] is True
        assert governance["latency_ms"] >= 0
        assert governance["scope"] == Scope.WORKSPACE_BOUND

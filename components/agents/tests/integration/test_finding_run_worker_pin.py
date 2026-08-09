"""A finding run is PINNED to its specialist — the planner can never re-route it.

Why this file exists — a real incident (2026-07-19). A detector delegated triage
work to the deep pipeline without pinning the worker. The LLM planner re-routed the
task by keyword to ``log_watch_agent``, an agent with none of the triage tools. It
did not fail: it *fabricated success*, silently, and the finding looked handled. The
fix was ``execute_plan_once(force_worker_agent_type=…)`` — a deterministic handoff
(LangGraph's ``Command(goto=…)`` equivalent) for the case where the caller already
KNOWS the specialist.

Every finding trigger — on-detection, the cadence, and the operator's on-demand
"draft a fix PR" — knows its specialist: the card declares it. So all three MUST
pin, and the pin has to survive the whole chain:

    card.metadata.agent_type
      → agent_context["worker_agent_type"]        (the dispatch builders)
      → AgentService._execute_deep               (reads it as the pin)
      → execute_plan_once(force_worker_agent_type=…)
      → the runner's worker_fn                    (overrides the planner's choice)

Each link is asserted below, plus a NEGATIVE control proving the pin is what does
the work. The seam most likely to rot silently is the third: drop the kwarg in
``_execute_deep`` and ``worker_agent_type`` becomes a decorative context key with
nothing reading it — every finding run goes back to being planner-routed, and
nothing anywhere raises.
"""

from __future__ import annotations

from unittest import mock

import pytest

from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec

pytestmark = pytest.mark.integration

# The exact mis-route from the incident: triage work handed to the log-watch agent.
_PINNED = "code_security_agent"
_PLANNER_CHOICE = "log_watch_agent"


def _stub_runner_environment(monkeypatch) -> list[str]:
    """Neutralise everything the runner touches except worker resolution.

    Returns the list that records which ``agent_type`` each worker was built for —
    the observation this whole file is about.
    """
    from langgraph.checkpoint.memory import MemorySaver

    import infrastructure.persistence.ai.agents.models as models
    from components.agents.infrastructure.adapters.langchain.deep import orchestrator
    from components.agents.infrastructure.adapters.langchain.deep import runner as deep_runner

    built_for: list[str] = []

    def recording_worker_factory(**kwargs):
        built_for.append(kwargs.get("agent_type"))

        def worker(state):
            task = state.get("task")
            return {"completed_tasks": [{"id": task.id if task else None, "status": "done"}], "artifacts": []}

        return worker

    monkeypatch.setattr(deep_runner, "build_worker_from_agent", recording_worker_factory)
    monkeypatch.setattr(deep_runner, "store_artifact", lambda *a, **kw: "artifact://stub")
    monkeypatch.setattr(deep_runner, "upsert_task_from_spec", lambda *a, **kw: None)
    monkeypatch.setattr(orchestrator, "default_checkpointer", lambda: MemorySaver())
    monkeypatch.setattr(
        models,
        "DeepRun",
        type(
            "DeepRunStub",
            (),
            {
                "STATUS_RUNNING": "running",
                "STATUS_COMPLETED": "completed",
                "objects": type(
                    "O",
                    (),
                    {
                        "update_or_create": lambda *a, **kw: (None, True),
                        "filter": lambda *a, **kw: type("Q", (), {"update": lambda *a, **kw: None})(),
                        "get_or_create": lambda *a, **kw: (None, True),
                    },
                )(),
            },
        ),
    )
    return built_for


def _misrouted_plan() -> PlanSpec:
    """A plan whose task the planner assigned to the WRONG specialist."""
    return PlanSpec(
        plan_id="plan-pin",
        goal="Triage finding 42",
        tasks=[TaskSpec(title="Triage the finding", agent_type=_PLANNER_CHOICE)],
    )


def test_the_runner_overrides_a_misrouted_task_with_the_pinned_specialist(monkeypatch):
    """THE guard: with the pin set, the planner's choice is discarded.

    This is the assertion that would have caught the 2026-07-19 fabricated-success
    incident: the task says ``log_watch_agent``, the run dispatches
    ``code_security_agent``.
    """
    from components.agents.infrastructure.adapters.langchain.deep.runner import execute_plan_once

    built_for = _stub_runner_environment(monkeypatch)

    execute_plan_once(
        plan=_misrouted_plan(),
        agent_type=_PINNED,
        user_id="user-1",
        workspace_id="workspace-1",
        sync_to_kanban=False,
        force_worker_agent_type=_PINNED,
    )

    assert _PINNED in built_for, "the pinned specialist never ran"
    assert _PLANNER_CHOICE not in built_for, (
        f"the planner's re-route to '{_PLANNER_CHOICE}' was honoured despite the pin — "
        "a finding run can be sent to an agent without the triage tools, which fabricates "
        "success silently (2026-07-19)"
    )


def test_without_the_pin_the_planner_choice_stands(monkeypatch):
    """Negative control — proves the assertion above is not vacuous.

    Unpinned, the runner genuinely honours the planner's per-task routing (the
    correct interactive behaviour). So the pin, and only the pin, is what makes a
    finding run deterministic.
    """
    from components.agents.infrastructure.adapters.langchain.deep.runner import execute_plan_once

    built_for = _stub_runner_environment(monkeypatch)

    execute_plan_once(
        plan=_misrouted_plan(),
        agent_type=_PINNED,
        user_id="user-1",
        workspace_id="workspace-1",
        sync_to_kanban=False,
        force_worker_agent_type=None,
    )

    assert _PLANNER_CHOICE in built_for


def test_deep_execution_forwards_the_context_pin_into_the_runner():
    """The rot-prone seam: ``worker_agent_type`` in the context MUST arrive as
    ``force_worker_agent_type`` on the runner call.

    Drop that kwarg and the context key becomes decorative — every finding run
    silently reverts to planner routing with nothing raising anywhere.
    """
    from components.agents.infrastructure.services.agents_service import AgentService

    agent_record = mock.Mock(
        id="agent-1",
        workspace_id="workspace-1",
        user_id="user-1",
        agent_type="code_security_agent",
        config={},
    )
    service = AgentService.__new__(AgentService)

    with (
        mock.patch(
            "components.agents.infrastructure.adapters.langchain.deep.llm_planner.plan_with_llm",
            return_value=_misrouted_plan(),
        ),
        mock.patch(
            "components.agents.infrastructure.adapters.langchain.deep.runner.execute_plan_once",
            return_value={"final_output": {"answer": "done"}},
        ) as execute,
        mock.patch("components.agents.application.services.deep_run_context.DeepRunContext"),
        mock.patch(
            "components.agents.infrastructure.adapters.deep_run_log_observability_adapter."
            "DeepRunLogObservabilityAdapter"
        ),
    ):
        service._execute_deep(
            agent_record=agent_record,
            agent_config={},
            query="Draft a fix for finding 42",
            performed_by="user-1",
            context={"mode": "deep", "worker_agent_type": _PINNED, "source": "on_demand.draft_fix"},
        )

    assert execute.call_args.kwargs["force_worker_agent_type"] == _PINNED, (
        "the deep executor dropped the caller's worker pin — the finding run would be "
        "handed back to the LLM planner to route"
    )


class TestEveryFindingTriggerPinsTheCardsSpecialist:
    """All three triggers derive the pin from the CARD, never a hardcoded agent."""

    def test_on_demand_draft_fix_pins_the_specialist_the_card_declares(self):
        from components.agents.infrastructure.services import finding_dispatch_service as fds

        context = fds.build_finding_agent_context(_PINNED, "42", {"payload": {"path": "app/x.py"}})
        assert context["worker_agent_type"] == _PINNED
        assert context["mode"] == "deep", "without deep mode the pin is never read (§5.13)"

    def test_batch_dispatch_pins_the_specialist_too(self):
        from components.agents.infrastructure.services import finding_dispatch_service as fds

        context = fds.build_agent_context("triage_agent", source="finding_raised")
        assert context["worker_agent_type"] == "triage_agent"
        assert context["mode"] == "deep"

    def test_the_pin_is_never_a_hardcoded_agent(self):
        """A second source's card must pin ITS OWN specialist — the mapping is data,
        so a new pillar is correct for free rather than silently inheriting SAST's."""
        from components.agents.infrastructure.services import finding_dispatch_service as fds

        for specialist in ("code_security_agent", "triage_agent", "optimization_agent"):
            assert fds.build_agent_context(specialist, source="x")["worker_agent_type"] == specialist

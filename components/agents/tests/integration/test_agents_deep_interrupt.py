"""Regression test for the deep-agent HITL approval gate.

The deep orchestrator inserts an `approval` node before the scheduler
when `approval_required=True`. That node calls `langgraph.interrupt()`
which pauses the graph at the checkpoint until a caller resumes it
with `Command(resume={"approved": True})`.

This test ensures the gate actually pauses execution and that resuming
with an approval lets the workers complete. It is gated on
`langgraph >= 0.2` (where `interrupt`/`Command` exist) — older
versions trigger an automatic skip so the suite stays green during
container rebuilds.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph.types")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command  # type: ignore

from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
    build_orchestrator,
)


def _make_plan() -> PlanSpec:
    return PlanSpec(
        plan_id="hitl-test",
        goal="Approve and run a single task.",
        tasks=[TaskSpec(id="t1", title="do thing")],
    )


def test_interrupt_pauses_then_resumes_with_approval():
    plan = _make_plan()
    completed: list[str] = []

    def planner_fn(_state):
        return plan

    def worker_fn(state):
        task = state.get("task")
        if task is not None:
            completed.append(task.id)
        return {}

    saver = MemorySaver()
    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        checkpointer=saver,
        approval_required=True,
    )
    config = {"configurable": {"thread_id": "hitl-1"}}

    # First invoke: graph runs planner → approval node → interrupt.
    # The result is the interrupt payload, NOT a finished state.
    first = graph.invoke({"plan": plan, "pending_tasks": list(plan.tasks)}, config=config)
    assert "__interrupt__" in str(first) or completed == [], (
        "approval node should pause before any worker runs"
    )
    assert completed == []

    # Resume with approval. The worker should now execute.
    graph.invoke(Command(resume={"approved": True}), config=config)
    assert completed == ["t1"], "worker must run after approval"


def test_interrupt_rejection_prevents_execution():
    plan = _make_plan()
    completed: list[str] = []

    def planner_fn(_state):
        return plan

    def worker_fn(state):
        task = state.get("task")
        if task is not None:
            completed.append(task.id)
        return {}

    saver = MemorySaver()
    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        checkpointer=saver,
        approval_required=True,
    )
    config = {"configurable": {"thread_id": "hitl-2"}}

    graph.invoke({"plan": plan, "pending_tasks": list(plan.tasks)}, config=config)
    graph.invoke(Command(resume={"approved": False}), config=config)
    assert completed == [], "rejected approval must skip worker execution"

from langgraph.checkpoint.memory import MemorySaver

from components.agents.infrastructure.adapters.langchain.deep.orchestrator import build_orchestrator
from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec


def test_orchestrator_respects_dependencies():
    call_order = []

    def planner_fn(_state):
        return PlanSpec(
            plan_id="plan-deps",
            goal="test deps",
            tasks=[
                TaskSpec(id="task-a", title="First task"),
                TaskSpec(id="task-b", title="Second task", depends_on=["task-a"]),
            ],
        )

    def worker_fn(state):
        task = state.get("task")
        if task:
            call_order.append(task.id)
        return {}

    graph = build_orchestrator(planner_fn=planner_fn, worker_fn=worker_fn, checkpointer=MemorySaver())
    graph.invoke({"run_id": "deps-run"}, config={"configurable": {"thread_id": "deps-thread"}})

    assert call_order == ["task-a", "task-b"]


def test_orchestrator_detects_blocked_dependencies():
    call_order = []

    def planner_fn(_state):
        return PlanSpec(
            plan_id="plan-blocked",
            goal="blocked deps",
            tasks=[
                TaskSpec(id="task-b", title="Blocked task", depends_on=["missing-task"]),
            ],
        )

    def worker_fn(state):
        task = state.get("task")
        if task:
            call_order.append(task.id)
        return {}

    graph = build_orchestrator(planner_fn=planner_fn, worker_fn=worker_fn, checkpointer=MemorySaver())
    state = graph.invoke({"run_id": "blocked-run"}, config={"configurable": {"thread_id": "blocked-thread"}})

    assert call_order == []
    assert state["run_metadata"]["plan_status"] == "blocked"
    assert state["run_metadata"]["blocked_task_ids"] == ["task-b"]

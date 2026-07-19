from langgraph.checkpoint.memory import MemorySaver
from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec
from components.agents.infrastructure.adapters.langchain.deep.runner import execute_plan_once


def test_execute_plan_once_returns_state(monkeypatch):
    # Keep this unit-level: stub the agent worker to avoid hitting external services.
    from components.agents.infrastructure.adapters.langchain.deep import runner as deep_runner
    from components.agents.infrastructure.adapters.langchain.deep import orchestrator

    def stub_worker(state):
        task = state.get("task")
        return {
            "completed_tasks": [{"id": task.id if task else None, "status": "done"}],
            "artifacts": [],
        }

    monkeypatch.setattr(deep_runner, "build_worker_from_agent", lambda **kwargs: stub_worker)
    monkeypatch.setattr(deep_runner, "store_artifact", lambda *args, **kwargs: "artifact://stub")
    monkeypatch.setattr(deep_runner, "upsert_task_from_spec", lambda *args, **kwargs: None)
    # Force an in-memory checkpointer; orchestrator imports default_checkpointer directly.
    monkeypatch.setattr(orchestrator, "default_checkpointer", lambda: MemorySaver())
    # Avoid hitting DB for DeepRun bookkeeping in this unit test.
    import infrastructure.persistence.ai.agents.models as models
    deep_run_stub = type(
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
    )
    monkeypatch.setattr(models, "DeepRun", deep_run_stub)

    user = type("UserStub", (), {"id": "user-1"})()
    workspace = type("WorkspaceStub", (), {"id": "workspace-1"})()
    plan = PlanSpec(plan_id="plan-test", goal="test", tasks=[TaskSpec(title="Do thing")])

    state = execute_plan_once(
        plan=plan,
        agent_type="task_agent",  # expects to exist; this test asserts shape only
        user_id=str(user.id),
        workspace_id=str(workspace.id),
        sync_to_kanban=False,
    )

    assert "completed_tasks" in state
    assert "artifacts" in state

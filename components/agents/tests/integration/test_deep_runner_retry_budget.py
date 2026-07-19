"""Retry + failure-budget wiring through the REAL ``execute_plan_once`` runner.

Complements the graph-level tests in
``components/agents/tests/unit/test_worker_retry_and_budget.py`` by driving
the full runner path: agent_config → build_orchestrator → worker retry →
run_metadata telemetry. The agent worker is stubbed (no LLM, no external
services); DeepRun bookkeeping is stubbed to stay off the DB, matching
``test_agents_deep_runner_stub.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec, WorkerResult
from components.agents.infrastructure.adapters.langchain.deep.runner import execute_plan_once


def _stub_deep_run(monkeypatch):
    import infrastructure.persistence.ai.agents.models as models

    deep_run_stub = type(
        "DeepRunStub",
        (),
        {
            "STATUS_RUNNING": "running",
            "STATUS_COMPLETED": "completed",
            "STATUS_FAILED": "failed",
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


class _FlakyWorker:
    """Fails each task with the scripted errors, then succeeds."""

    def __init__(self, errors_by_task):
        self.calls: list[str] = []
        self._errors = {k: list(v) for k, v in errors_by_task.items()}

    def __call__(self, state):
        task = state.get("task")
        task_id = str(task.id)
        self.calls.append(task_id)
        queued = self._errors.get(task_id)
        if queued:
            raise queued.pop(0)
        return {
            "completed_tasks": [WorkerResult(task_id=task_id, summary=f"done {task_id}")],
            "artifacts": [],
        }


def _run(monkeypatch, worker, *, agent_config=None, tasks=None):
    from components.agents.infrastructure.adapters.langchain.deep import orchestrator
    from components.agents.infrastructure.adapters.langchain.deep import runner as deep_runner

    monkeypatch.setattr(deep_runner, "build_worker_from_agent", lambda **kwargs: worker)
    monkeypatch.setattr(deep_runner, "store_artifact", lambda *args, **kwargs: "artifact://stub")
    monkeypatch.setattr(deep_runner, "upsert_task_from_spec", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator, "default_checkpointer", lambda: MemorySaver())
    # Zero out the retry backoff so the test doesn't sleep.
    original_build = orchestrator.build_orchestrator
    monkeypatch.setattr(
        deep_runner,
        "build_orchestrator",
        lambda **kwargs: original_build(**{**kwargs, "retry_backoff_seconds": 0.0}),
    )
    _stub_deep_run(monkeypatch)

    plan = PlanSpec(
        plan_id="plan-retry",
        goal="test retries",
        tasks=tasks or [TaskSpec(id="t1", title="Do thing")],
    )
    return execute_plan_once(
        plan=plan,
        agent_type="task_agent",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_config=agent_config,
        sync_to_kanban=False,
        use_llm_synthesizer=False,
    )


def test_transient_failure_retries_and_run_completes(monkeypatch):
    worker = _FlakyWorker({"t1": [TimeoutError("read timed out")]})
    state = _run(monkeypatch, worker)
    assert worker.calls == ["t1", "t1"]  # default max_worker_retries=1
    run_metadata = state.get("run_metadata") or {}
    assert run_metadata.get("worker_retries") == {"t1": 1}
    assert not run_metadata.get("worker_failures")
    assert run_metadata.get("plan_status") == "completed"


def test_agent_config_can_disable_retries(monkeypatch):
    worker = _FlakyWorker({"t1": [TimeoutError("read timed out")]})
    state = _run(monkeypatch, worker, agent_config={"max_worker_retries": 0})
    assert worker.calls == ["t1"]
    run_metadata = state.get("run_metadata") or {}
    record = (run_metadata.get("worker_failures") or {}).get("t1") or {}
    assert record.get("transient") is True
    assert record.get("retries") == 0


def test_agent_config_retries_are_hard_capped(monkeypatch):
    from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
        MAX_WORKER_RETRIES_HARD_CAP,
    )

    worker = _FlakyWorker({"t1": [TimeoutError(f"t/o {i}") for i in range(10)]})
    state = _run(monkeypatch, worker, agent_config={"max_worker_retries": 99})
    assert len(worker.calls) == 1 + MAX_WORKER_RETRIES_HARD_CAP
    run_metadata = state.get("run_metadata") or {}
    assert (run_metadata.get("worker_failures") or {}).get("t1", {}).get("retries") == MAX_WORKER_RETRIES_HARD_CAP


def test_concurrent_worker_failures_do_not_kill_the_run(monkeypatch):
    """Two tasks failing in the same Send superstep previously raised
    InvalidUpdateError on the last-value failure channel; through the real
    runner the run must complete with both failures recorded."""
    worker = _FlakyWorker({"t1": [ValueError("boom 1")], "t2": [ValueError("boom 2")]})
    state = _run(
        monkeypatch,
        worker,
        agent_config={"max_worker_retries": 0},
        tasks=[TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")],
    )
    run_metadata = state.get("run_metadata") or {}
    assert set(run_metadata.get("worker_failures") or {}) == {"t1", "t2"}

"""The RUN row records the autonomy it executed under (ADR 0035 D5).

D5 says the mode is recorded "on the run AND on every tool observation". Only
the observation half was built. `ai_deeprun.autonomy_mode` existed as a column
that nothing wrote — 2098 of 2098 rows empty on the live cluster.

A column nobody fills is worse than no column: it passes a schema review looking
like provenance, and answers nothing on the day someone asks what a run was
permitted to do. So these drive the REAL ``execute_plan_once`` and assert on the
kwargs that reach the DeepRun write, rather than on any intermediate that could
report success while the row stayed blank.

The stamp lands at the RUNNING transition, not at PENDING. A run that has not
started has not executed under anything, and writing a mode there would be a
claim about work that never happened.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec, WorkerResult
from components.agents.infrastructure.adapters.langchain.deep.runner import execute_plan_once

pytestmark = [pytest.mark.integration]


def _capturing_deep_run(monkeypatch):
    """Stub DeepRun, keeping every ``update_or_create`` call for assertion."""
    import infrastructure.persistence.ai.agents.models as models

    calls: list[dict] = []

    def _update_or_create(*_args, **kwargs):
        calls.append(kwargs)
        return (None, True)

    stub = type(
        "DeepRunStub",
        (),
        {
            "STATUS_PENDING": "pending",
            "STATUS_RUNNING": "running",
            "STATUS_COMPLETED": "completed",
            "STATUS_FAILED": "failed",
            "objects": type(
                "O",
                (),
                {
                    "update_or_create": staticmethod(_update_or_create),
                    "filter": lambda *a, **kw: type("Q", (), {"update": lambda *a, **kw: None})(),
                    "get_or_create": lambda *a, **kw: (None, True),
                },
            )(),
        },
    )
    monkeypatch.setattr(models, "DeepRun", stub)
    return calls


class _OkWorker:
    def __call__(self, state):
        task = state.get("task")
        return {
            "completed_tasks": [WorkerResult(task_id=str(task.id), summary="done")],
            "artifacts": [],
        }


def _run(monkeypatch, *, agent_config=None, workspace_mode="assist", mode_raises=False):
    from components.agents.infrastructure.adapters.langchain import autonomy_resolution
    from components.agents.infrastructure.adapters.langchain.deep import orchestrator
    from components.agents.infrastructure.adapters.langchain.deep import runner as deep_runner

    monkeypatch.setattr(deep_runner, "build_worker_from_agent", lambda **kwargs: _OkWorker())
    monkeypatch.setattr(deep_runner, "store_artifact", lambda *a, **kw: "artifact://stub")
    monkeypatch.setattr(deep_runner, "upsert_task_from_spec", lambda *a, **kw: None)
    monkeypatch.setattr(orchestrator, "default_checkpointer", lambda: MemorySaver())

    # The workspace setting and the principal lookup are the two inputs the
    # resolver reads; both are stubbed so the test states the mode, not the DB.
    def _adapter_get_mode(self, *, workspace_id):
        if mode_raises:
            raise RuntimeError("settings read failed")
        return workspace_mode

    import components.agents.infrastructure.adapters.workspace_autonomy_adapter as adapter_module

    monkeypatch.setattr(adapter_module.WorkspaceAutonomyAdapter, "get_mode", _adapter_get_mode)
    monkeypatch.setattr(autonomy_resolution, "resolve_run_mode", autonomy_resolution.resolve_run_mode)

    import components.agents.infrastructure.adapters.langchain.base as base_module

    monkeypatch.setattr(base_module, "is_ai_service_principal", lambda *a, **kw: False)

    calls = _capturing_deep_run(monkeypatch)
    execute_plan_once(
        plan=PlanSpec(plan_id="p-1", goal="g", tasks=[TaskSpec(id="t1", title="Do thing")]),
        agent_type="task_agent",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_config=agent_config,
        sync_to_kanban=False,
        use_llm_synthesizer=False,
    )
    return calls


def _running_defaults(calls):
    """The defaults from the write that flipped the run to RUNNING."""
    running = [c for c in calls if (c.get("defaults") or {}).get("status") == "running"]
    assert running, "the runner never wrote a RUNNING row"
    return running[0]["defaults"]


class TestTheRunRowCarriesTheMode:
    def test_a_normal_run_records_assist(self, monkeypatch):
        defaults = _running_defaults(_run(monkeypatch, workspace_mode="assist"))

        assert defaults["autonomy_mode"] == "assist"

    def test_a_manual_workspace_records_manual(self, monkeypatch):
        """The row must describe the policy the run was actually held to —
        which for a MANUAL workspace means no write executed."""
        defaults = _running_defaults(_run(monkeypatch, workspace_mode="manual"))

        assert defaults["autonomy_mode"] == "manual"

    def test_an_evaluation_run_records_evaluation(self, monkeypatch):
        """Stricter than any workspace setting, and recorded distinctly:
        calling it ASSIST would overstate what it was permitted to do."""
        defaults = _running_defaults(
            _run(monkeypatch, agent_config={"execution_mode": "evaluation"}, workspace_mode="autonomous")
        )

        assert defaults["autonomy_mode"] == "evaluation"

    def test_the_mode_rides_the_same_write_as_the_status(self, monkeypatch):
        """One write, not a follow-up UPDATE that could fail on its own and
        leave a RUNNING row with no recorded policy."""
        defaults = _running_defaults(_run(monkeypatch))

        assert defaults["status"] == "running"
        assert "autonomy_mode" in defaults


class TestAnUnreadableSettingIsNotRecordedAsAssist:
    def test_a_failed_read_records_unknown(self, monkeypatch):
        """The row says "we do not know" rather than asserting a mode we could
        not confirm — matching what the gate does with the same failure, which
        is to hold writes."""
        defaults = _running_defaults(_run(monkeypatch, mode_raises=True))

        assert defaults["autonomy_mode"] == "unknown"

    def test_it_is_never_silently_blank(self, monkeypatch):
        """Blank means "written before this field existed". A run we observed
        must never be indistinguishable from one that predates the column."""
        defaults = _running_defaults(_run(monkeypatch, mode_raises=True))

        assert defaults["autonomy_mode"] != ""

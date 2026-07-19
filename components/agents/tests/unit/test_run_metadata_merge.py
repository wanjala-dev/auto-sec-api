"""``PlanState.run_metadata`` merge semantics (task #57).

The rubric middleware's ``rubric_verdicts`` and the critic's ``critic_scores``
are stamped onto worker state deltas, but workers are fanned out via
``Send`` — their input state carries NO run_metadata. On the old plain
last-value channel that meant:

1. Two concurrent workers returning ``run_metadata`` raised
   ``InvalidUpdateError`` and killed the run.
2. Sequential workers clobbered each other's stamps, so only the LAST task's
   verdict ever reached the persisted ``DeepRun.state``.

These tests pin the fix — the ``merge_run_metadata`` reducer — at both
levels: the pure reducer, and end-to-end through ``build_orchestrator`` with
fake workers (no LLM, no DB: in-memory checkpointer).
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from components.agents.domain.value_objects.plan_schemas import (
    PlanSpec,
    TaskSpec,
    WorkerResult,
    merge_run_metadata,
)
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import build_orchestrator


class TestMergeRunMetadataReducer:
    def test_later_scalar_keys_win(self):
        merged = merge_run_metadata({"plan_status": "running", "iteration_count": 1}, {"plan_status": "completed"})
        assert merged == {"plan_status": "completed", "iteration_count": 1}

    def test_nested_dicts_union_by_key(self):
        merged = merge_run_metadata(
            {"rubric_verdicts": {"t1": {"verdict": "satisfied"}}},
            {"rubric_verdicts": {"t2": {"verdict": "needs_revision"}}},
        )
        assert merged["rubric_verdicts"] == {
            "t1": {"verdict": "satisfied"},
            "t2": {"verdict": "needs_revision"},
        }

    def test_nested_same_key_later_wins(self):
        merged = merge_run_metadata(
            {"rubric_verdicts": {"t1": {"verdict": "needs_revision", "iterations": 1}}},
            {"rubric_verdicts": {"t1": {"verdict": "satisfied", "iterations": 2}}},
        )
        assert merged["rubric_verdicts"]["t1"] == {"verdict": "satisfied", "iterations": 2}

    def test_non_dict_value_replaces_dict(self):
        # A node replacing a dict value with a scalar is later-wins, not an error.
        merged = merge_run_metadata({"approval": {"approved": True}}, {"approval": "revoked"})
        assert merged["approval"] == "revoked"

    def test_none_tolerant_both_sides(self):
        assert merge_run_metadata(None, None) == {}
        assert merge_run_metadata(None, {"a": 1}) == {"a": 1}
        assert merge_run_metadata({"a": 1}, None) == {"a": 1}

    def test_inputs_not_mutated(self):
        current = {"rubric_verdicts": {"t1": {"verdict": "satisfied"}}}
        update = {"rubric_verdicts": {"t2": {"verdict": "failed"}}}
        merge_run_metadata(current, update)
        assert current == {"rubric_verdicts": {"t1": {"verdict": "satisfied"}}}
        assert update == {"rubric_verdicts": {"t2": {"verdict": "failed"}}}


def _stamping_worker(metadata_key: str):
    """A fake worker that stamps a per-task entry under *metadata_key* —
    exactly the delta shape the rubric stamp (adapters.py) and the critic
    stamp (critic.py) return: seeded from the worker's own input state,
    which for a ``Send`` fan-out carries no run_metadata."""

    def worker_fn(state):
        task = state.get("task")
        run_metadata = dict(state.get("run_metadata") or {})
        stamps = dict(run_metadata.get(metadata_key) or {})
        stamps[str(task.id)] = {"verdict": "satisfied", "iterations": 1, "task": task.title}
        run_metadata[metadata_key] = stamps
        return {
            "completed_tasks": [WorkerResult(task_id=task.id, summary=f"done {task.id}")],
            "run_metadata": run_metadata,
        }

    return worker_fn


def _run_graph(tasks: list[TaskSpec], worker_fn):
    def planner_fn(state):
        return PlanSpec(plan_id="p1", goal="goal", tasks=tasks)

    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        checkpointer=MemorySaver(),
    )
    return graph.invoke(
        {"plan": None, "pending_tasks": [], "completed_task_ids": [], "run_id": "r1", "run_context": {}},
        config={"configurable": {"thread_id": "t-run-metadata-merge"}},
    )


class TestRunMetadataSurvivesOrchestrator:
    def test_sequential_workers_both_stamps_survive(self):
        """Task B's stamp must NOT clobber task A's (the old last-writer-wins
        behavior kept only the final task's verdict)."""
        tasks = [
            TaskSpec(id="t1", title="one"),
            TaskSpec(id="t2", title="two", depends_on=["t1"]),
        ]
        final = _run_graph(tasks, _stamping_worker("rubric_verdicts"))
        verdicts = (final.get("run_metadata") or {}).get("rubric_verdicts") or {}
        assert set(verdicts) == {"t1", "t2"}
        assert verdicts["t1"]["verdict"] == "satisfied"
        assert verdicts["t2"]["verdict"] == "satisfied"

    def test_concurrent_workers_both_stamps_survive(self):
        """Two ready tasks fan out via Send in ONE superstep. On the plain
        channel this raised InvalidUpdateError; the reducer must union both."""
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")]
        final = _run_graph(tasks, _stamping_worker("rubric_verdicts"))
        verdicts = (final.get("run_metadata") or {}).get("rubric_verdicts") or {}
        assert set(verdicts) == {"t1", "t2"}

    def test_critic_scores_survive_via_same_mechanism(self):
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")]
        final = _run_graph(tasks, _stamping_worker("critic_scores"))
        scores = (final.get("run_metadata") or {}).get("critic_scores") or {}
        assert set(scores) == {"t1", "t2"}

    def test_scheduler_and_synthesizer_keys_coexist_with_stamps(self):
        """The scheduler's bookkeeping (plan_status, iteration_count) and the
        worker stamps must not drop each other — no node may silently lose
        another node's keys."""
        tasks = [TaskSpec(id="t1", title="one")]
        final = _run_graph(tasks, _stamping_worker("rubric_verdicts"))
        run_metadata = final.get("run_metadata") or {}
        assert "rubric_verdicts" in run_metadata
        assert run_metadata.get("plan_status") == "completed"
        assert isinstance(run_metadata.get("iteration_count"), int)

    def test_final_output_carries_merged_metadata(self):
        """The no-op synthesizer snapshots state.run_metadata into
        final_output — the persisted DeepRun.state must expose the verdicts
        through both paths."""
        tasks = [TaskSpec(id="t1", title="one")]
        final = _run_graph(tasks, _stamping_worker("rubric_verdicts"))
        final_output = final.get("final_output") or {}
        assert (final_output.get("run_metadata") or {}).get("rubric_verdicts", {}).get("t1")

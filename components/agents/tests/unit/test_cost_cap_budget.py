"""Per-run cost cap + spend accumulation (task #46).

Drives the REAL ``build_orchestrator`` graph (fake workers, no LLM, no DB —
in-memory checkpointer) and pins:

1. worker-stamped ``cost_usd_records`` union across concurrent ``Send``
   workers (reducer-merged, never clobbered) and the scheduler's derived
   ``cost_usd_total``;
2. ``ExecutionBudget.max_cost_usd`` genuinely trips: pending work is dropped,
   the run reports honest budget exhaustion, nothing is fabricated;
3. the cap default is OFF (``None``) — existing callers see no behaviour
   change;
4. ``worker_cost_record`` prices only what it can substantiate (single-model
   telemetry) and never fabricates a cost for ambiguous/multi-model runs.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from components.agents.domain.value_objects.plan_schemas import (
    ExecutionBudget,
    PlanSpec,
    TaskSpec,
    WorkerResult,
)
from components.agents.infrastructure.adapters.langchain.deep.costing import worker_cost_record
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
    _check_budget,
    _total_run_cost_usd,
    build_orchestrator,
)


def _costing_worker(cost_per_task: float):
    """Fake worker: succeeds and stamps a cost record for its task."""

    def worker(state):
        task = state.get("task")
        task_id = str(task.id)
        return {
            "completed_tasks": [WorkerResult(task_id=task_id, summary=f"done {task.title}")],
            "run_metadata": {"cost_usd_records": {task_id: {"cost_usd": cost_per_task, "input_tokens": 100}}},
        }

    return worker


def _run_graph(tasks, worker_fn, *, budget=None, thread_id="t-cost"):
    def planner_fn(state):
        return PlanSpec(plan_id="p-cost", goal="goal", tasks=tasks)

    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        checkpointer=MemorySaver(),
        budget=budget,
        max_replans=0,
        retry_backoff_seconds=0.0,
    )
    return graph.invoke(
        {"plan": None, "pending_tasks": [], "completed_task_ids": [], "run_id": "r-cost", "run_context": {}},
        config={"configurable": {"thread_id": thread_id}},
    )


class TestTotalRunCost:
    def test_derives_from_records_and_skips_unpriced(self):
        state = {
            "run_metadata": {
                "cost_usd_records": {
                    "planner": {"cost_usd": 0.01},
                    "task-1": {"cost_usd": 0.25},
                    "task-2": {"cost_usd": None, "input_tokens": 500},  # unpriced — not fabricated
                    "task-3": "garbage",  # malformed — ignored
                }
            }
        }
        assert _total_run_cost_usd(state) == pytest.approx(0.26)

    def test_empty_state_is_zero(self):
        assert _total_run_cost_usd({}) == 0.0


class TestCheckBudgetCostCap:
    def _state(self, *, max_cost_usd, spent):
        budget = ExecutionBudget(max_cost_usd=max_cost_usd)
        return {
            "budget": budget.model_dump(),
            "iteration_count": 1,
            "completed_task_ids": [],
            "pending_tasks": [],
            "run_metadata": {"cost_usd_records": {"t": {"cost_usd": spent}}},
        }

    def test_trips_when_spend_reaches_cap(self):
        reason = _check_budget(self._state(max_cost_usd=0.5, spent=0.6))
        assert reason is not None and "max_cost_usd" in reason

    def test_does_not_trip_below_cap(self):
        assert _check_budget(self._state(max_cost_usd=0.5, spent=0.4)) is None

    def test_cap_default_none_never_trips(self):
        assert ExecutionBudget().max_cost_usd is None
        assert _check_budget(self._state(max_cost_usd=None, spent=10_000.0)) is None

    def test_old_checkpoint_budget_dict_without_cap_still_parses(self):
        # Budget dicts persisted before the field existed round-trip cleanly.
        legacy = {"max_iterations": 50, "max_tasks": 100, "time_budget_seconds": 300.0, "max_worker_failures": 10}
        state = {"budget": legacy, "iteration_count": 1, "run_metadata": {}}
        assert _check_budget(state) is None


class TestGraphCostAccumulation:
    def test_concurrent_worker_records_union_and_total_derived(self):
        tasks = [TaskSpec(id="a", title="A"), TaskSpec(id="b", title="B")]
        state = _run_graph(tasks, _costing_worker(0.6))

        records = state["run_metadata"]["cost_usd_records"]
        assert set(records) == {"a", "b"}  # both survived the reducer merge
        assert state["run_metadata"]["cost_usd_total"] == pytest.approx(1.2)
        # No cap set → the run completed everything.
        assert len(state.get("completed_task_ids") or []) == 2
        assert "budget_exceeded_reason" not in state["run_metadata"]

    def test_cost_cap_trips_and_drops_pending_work_honestly(self):
        # b depends on a — a's spend (0.6) trips the 0.5 cap before b runs.
        tasks = [TaskSpec(id="a", title="A"), TaskSpec(id="b", title="B", depends_on=["a"])]
        state = _run_graph(tasks, _costing_worker(0.6), budget=ExecutionBudget(max_cost_usd=0.5))

        run_metadata = state["run_metadata"]
        assert run_metadata["plan_status"] == "budget_exceeded"
        assert "max_cost_usd" in run_metadata["budget_exceeded_reason"]
        # b was never dispatched, and the final output says so honestly.
        assert state.get("completed_task_ids") == ["a"]
        pending_ids = [t.id for t in state.get("pending_tasks") or []]
        assert pending_ids == ["b"]
        assert "max_cost_usd" in (state["final_output"].get("budget_exceeded") or "")

    def test_planner_seed_counts_toward_the_cap(self):
        # A pre-seeded planner record + one worker record together trip the cap.
        tasks = [TaskSpec(id="a", title="A"), TaskSpec(id="b", title="B", depends_on=["a"])]

        def planner_fn(state):
            return PlanSpec(plan_id="p-cost", goal="goal", tasks=tasks)

        graph = build_orchestrator(
            planner_fn=planner_fn,
            worker_fn=_costing_worker(0.3),
            checkpointer=MemorySaver(),
            budget=ExecutionBudget(max_cost_usd=0.5),
            max_replans=0,
        )
        state = graph.invoke(
            {
                "plan": None,
                "pending_tasks": [],
                "completed_task_ids": [],
                "run_id": "r-seed",
                "run_context": {},
                "run_metadata": {"cost_usd_records": {"planner": {"cost_usd": 0.25}}},
            },
            config={"configurable": {"thread_id": "t-seed"}},
        )
        run_metadata = state["run_metadata"]
        # 0.25 planner + 0.3 task a = 0.55 >= 0.5 → b never ran.
        assert "max_cost_usd" in (run_metadata.get("budget_exceeded_reason") or "")
        assert "planner" in run_metadata["cost_usd_records"]
        assert state.get("completed_task_ids") == ["a"]


class TestWorkerCostRecord:
    def _response(self, *, tokens, models):
        return {"success": True, "telemetry": {"tokens": tokens, "models": models, "llm_calls": 3}}

    def test_prices_single_model_telemetry(self):
        with mock.patch(
            "components.agents.infrastructure.adapters.langchain.deep.costing.cost_usd_for_tokens",
            return_value=0.0123,
        ) as pricer:
            record = worker_cost_record(
                self._response(tokens={"input_tokens": 900, "output_tokens": 100}, models={"gpt-4o": 3})
            )
        pricer.assert_called_once_with("gpt-4o", 900, 100)
        assert record == {
            "cost_usd": 0.0123,
            "input_tokens": 900,
            "output_tokens": 100,
            "model": "gpt-4o",
            "llm_calls": 3,
            "source": "worker_telemetry",
        }

    def test_multi_model_records_tokens_but_never_fabricates_cost(self):
        record = worker_cost_record(
            self._response(tokens={"input_tokens": 900, "output_tokens": 100}, models={"gpt-4o": 2, "gpt-4o-mini": 1})
        )
        assert record["cost_usd"] is None
        assert record["model"] is None
        assert record["input_tokens"] == 900

    def test_no_telemetry_or_no_tokens_is_none(self):
        assert worker_cost_record({"success": True}) is None
        assert worker_cost_record(None) is None
        assert worker_cost_record(self._response(tokens={"input_tokens": 0, "output_tokens": 0}, models={})) is None

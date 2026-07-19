"""Deep-runner retry + failure-budget enforcement (task #45).

The old ``worker_failure_count`` was a last-value channel computed off the
worker's empty ``Send`` payload — it could never exceed 1 (so
``ExecutionBudget.max_worker_failures`` could NEVER trip) and two concurrently
failing workers raised ``InvalidUpdateError``. Failure records now live in
``run_metadata["worker_failures"]`` (united by the ``merge_run_metadata``
reducer); the count is derived from the records minus the
``worker_failures_baseline`` watermark stamped at replan.

These tests drive the REAL ``build_orchestrator`` graph (fake workers, no
LLM, no DB — in-memory checkpointer) and pin:

1. failure counts accumulate across concurrent AND sequential worker
   failures, and genuinely trip ``max_worker_failures``;
2. replan bookkeeping "resets" the count via the baseline watermark without
   deleting telemetry;
3. transient failures retry (bounded, hard-capped, time-budget-aware) while
   deterministic failures never retry;
4. the synthesizer reports budget exhaustion honestly instead of fabricating
   success.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from components.agents.domain.value_objects.plan_schemas import (
    ExecutionBudget,
    PlanSpec,
    TaskSpec,
    WorkerResult,
)
from components.agents.infrastructure.adapters.langchain.deep.orchestrator import (
    MAX_WORKER_RETRIES_HARD_CAP,
    _derived_worker_failure_count,
    _is_transient_worker_error,
    build_orchestrator,
    llm_synthesizer,
)


def _run_graph(
    tasks: list[TaskSpec],
    worker_fn,
    *,
    budget: ExecutionBudget | None = None,
    max_replans: int = 0,
    max_worker_retries: int = 1,
    thread_id: str = "t-retry-budget",
):
    def planner_fn(state):
        return PlanSpec(plan_id="p1", goal="goal", tasks=tasks)

    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        checkpointer=MemorySaver(),
        budget=budget,
        max_replans=max_replans,
        max_worker_retries=max_worker_retries,
        retry_backoff_seconds=0.0,  # keep tests fast; backoff is not under test
    )
    return graph.invoke(
        {"plan": None, "pending_tasks": [], "completed_task_ids": [], "run_id": "r1", "run_context": {}},
        config={"configurable": {"thread_id": thread_id}},
    )


class _CountingWorker:
    """Fake worker with per-call scripting: raise from ``errors`` until they
    run out, then succeed. ``errors`` may be keyed per task id."""

    def __init__(self, errors_by_task: dict[str, list[BaseException]] | None = None, sleep: float = 0.0):
        self.calls: list[str] = []
        self._errors = {k: list(v) for k, v in (errors_by_task or {}).items()}
        self._sleep = sleep

    def __call__(self, state):
        task = state.get("task")
        task_id = str(task.id)
        self.calls.append(task_id)
        if self._sleep:
            time.sleep(self._sleep)
        queued = self._errors.get(task_id)
        if queued:
            raise queued.pop(0)
        return {"completed_tasks": [WorkerResult(task_id=task_id, summary=f"done {task_id}")]}


class TestTransientClassification:
    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("read timed out"),
            ConnectionError("connection dropped"),
            ConnectionResetError("peer reset"),
            type("RateLimitError", (Exception,), {})("quota"),
            type("APIConnectionError", (Exception,), {})("no route"),
            type("ServiceUnavailableError", (Exception,), {})("upstream down"),
            RuntimeError("Rate limit exceeded, please slow down"),
            RuntimeError("The upstream provider is temporarily unavailable"),
            RuntimeError("HTTP error: 502 Bad Gateway"),
            Exception("Request timed out after 60s"),
        ],
    )
    def test_transient_shapes_retry(self, exc):
        assert _is_transient_worker_error(exc)

    @pytest.mark.parametrize(
        "exc",
        [
            ValueError("tool refused: amount must be positive"),
            KeyError("workspace_id"),
            PermissionError("Agent type 'x' is not allowed for this run."),
            RuntimeError("invalid request: unknown parameter 'foo'"),
            TypeError("unsupported operand"),
            Exception("the model declined to produce output for this input"),
        ],
    )
    def test_deterministic_shapes_do_not_retry(self, exc):
        assert not _is_transient_worker_error(exc)

    def test_permission_error_never_transient_even_with_transient_message(self):
        # Conservative: an explicit denial stays deterministic no matter
        # how its message reads.
        assert not _is_transient_worker_error(PermissionError("connection error: agent not allowed"))


class TestFailureCountTripsBudget:
    def test_concurrent_failures_accumulate_and_trip_cap(self):
        """Two failing workers in ONE Send superstep must (a) not raise
        InvalidUpdateError and (b) count as 2, tripping max_worker_failures=2.
        On the old last-value channel the count never exceeded 1."""
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")]
        worker = _CountingWorker(
            {"t1": [ValueError("boom 1")], "t2": [ValueError("boom 2")]},
        )
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(max_worker_failures=2),
            max_worker_retries=0,
        )
        run_metadata = final.get("run_metadata") or {}
        assert set(run_metadata.get("worker_failures") or {}) == {"t1", "t2"}
        assert run_metadata.get("plan_status") == "budget_exceeded"
        assert "max_worker_failures" in (run_metadata.get("budget_exceeded_reason") or "")

    def test_sequential_failures_accumulate_and_trip_cap(self):
        """Task B failing AFTER task A must count 2 total — the old channel
        reset to 1 on every failure because each worker seeds from its empty
        Send payload."""
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two", depends_on=["t1"])]
        worker = _CountingWorker(
            {"t1": [ValueError("boom 1")], "t2": [ValueError("boom 2")]},
        )
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(max_worker_failures=2),
            max_worker_retries=0,
        )
        run_metadata = final.get("run_metadata") or {}
        assert set(run_metadata.get("worker_failures") or {}) == {"t1", "t2"}
        assert "max_worker_failures" in (run_metadata.get("budget_exceeded_reason") or "")

    def test_tripped_cap_stops_further_dispatch(self):
        """Once the failure cap trips, remaining ready tasks are NOT
        dispatched — the scheduler routes straight to the synthesizer."""
        tasks = [
            TaskSpec(id="t1", title="one"),
            TaskSpec(id="t2", title="two"),
            TaskSpec(id="t3", title="three", depends_on=["t1"]),
        ]
        worker = _CountingWorker(
            {"t1": [ValueError("boom 1")], "t2": [ValueError("boom 2")]},
        )
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(max_worker_failures=2),
            max_worker_retries=0,
        )
        assert worker.calls == ["t1", "t2"] or sorted(worker.calls) == ["t1", "t2"]
        assert "t3" not in worker.calls
        run_metadata = final.get("run_metadata") or {}
        assert run_metadata.get("plan_status") == "budget_exceeded"

    def test_below_cap_does_not_trip(self):
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")]
        worker = _CountingWorker({"t1": [ValueError("boom 1")]})
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(max_worker_failures=2),
            max_worker_retries=0,
        )
        run_metadata = final.get("run_metadata") or {}
        assert run_metadata.get("plan_status") == "completed"
        assert set(run_metadata.get("worker_failures") or {}) == {"t1"}

    def test_failure_records_carry_telemetry(self):
        tasks = [TaskSpec(id="t1", title="one")]
        worker = _CountingWorker({"t1": [ValueError("boom")]})
        final = _run_graph(tasks, worker, max_worker_retries=0)
        record = (final.get("run_metadata") or {})["worker_failures"]["t1"]
        assert record["task_id"] == "t1"
        assert record["error"] == "boom"
        assert record["error_type"] == "ValueError"
        assert record["transient"] is False
        assert record["retries"] == 0
        # Legacy per-task key preserved for existing consumers.
        assert (final.get("run_metadata") or {}).get("worker_error_t1") == "boom"


class TestReplanReset:
    def test_replan_stamps_baseline_and_resets_derived_count(self):
        """Failures trigger one replan; after ``replan_bookkeeping`` the
        derived count must be 0 (baseline watermark) WITHOUT deleting the
        failure records, and the rerun must not loop or trip the budget."""
        tasks = [TaskSpec(id="t1", title="one"), TaskSpec(id="t2", title="two")]
        worker = _CountingWorker(
            {"t1": [ValueError("boom 1")], "t2": [ValueError("boom 2")]},
        )
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(max_worker_failures=10),
            max_replans=1,
            max_worker_retries=0,
        )
        run_metadata = final.get("run_metadata") or {}
        assert run_metadata.get("replans_done") == 1
        assert run_metadata.get("worker_failures_baseline") == 2
        # Telemetry survives the "reset" — records are never deleted.
        assert set(run_metadata.get("worker_failures") or {}) == {"t1", "t2"}
        # Post-replan the derived count is 0, so the budget must not trip.
        assert run_metadata.get("plan_status") == "completed"
        assert _derived_worker_failure_count(final) == 0

    def test_derived_count_counts_only_records_above_baseline(self):
        state = {
            "run_metadata": {
                "worker_failures": {"a": {}, "b": {}, "c": {}},
                "worker_failures_baseline": 2,
            }
        }
        assert _derived_worker_failure_count(state) == 1

    def test_derived_count_falls_back_to_legacy_channel(self):
        assert _derived_worker_failure_count({"worker_failure_count": 3}) == 3
        assert _derived_worker_failure_count({}) == 0


class TestTransientRetry:
    def test_transient_error_retries_once_then_succeeds(self):
        tasks = [TaskSpec(id="t1", title="one")]
        worker = _CountingWorker({"t1": [TimeoutError("read timed out")]})
        final = _run_graph(tasks, worker, max_worker_retries=1)
        assert worker.calls == ["t1", "t1"]
        run_metadata = final.get("run_metadata") or {}
        assert run_metadata.get("worker_retries") == {"t1": 1}
        assert not run_metadata.get("worker_failures")
        assert run_metadata.get("plan_status") == "completed"
        summaries = [r.summary for r in final.get("completed_tasks") or []]
        assert summaries == ["done t1"]

    def test_deterministic_error_does_not_retry(self):
        tasks = [TaskSpec(id="t1", title="one")]
        worker = _CountingWorker({"t1": [ValueError("tool refused")]})
        final = _run_graph(tasks, worker, max_worker_retries=2)
        assert worker.calls == ["t1"]
        record = (final.get("run_metadata") or {})["worker_failures"]["t1"]
        assert record["transient"] is False
        assert record["retries"] == 0

    def test_transient_error_exhausts_retries_then_records_failure(self):
        tasks = [TaskSpec(id="t1", title="one")]
        worker = _CountingWorker({"t1": [TimeoutError("t/o 1"), TimeoutError("t/o 2"), TimeoutError("t/o 3")]})
        final = _run_graph(tasks, worker, max_worker_retries=2)
        assert worker.calls == ["t1", "t1", "t1"]  # 1 attempt + 2 retries
        run_metadata = final.get("run_metadata") or {}
        record = run_metadata["worker_failures"]["t1"]
        assert record["transient"] is True
        assert record["retries"] == 2
        assert run_metadata.get("worker_retries") == {"t1": 2}

    def test_retries_hard_capped_regardless_of_config(self):
        tasks = [TaskSpec(id="t1", title="one")]
        errors = [TimeoutError(f"t/o {i}") for i in range(10)]
        worker = _CountingWorker({"t1": errors})
        _run_graph(tasks, worker, max_worker_retries=99)
        assert len(worker.calls) == 1 + MAX_WORKER_RETRIES_HARD_CAP

    def test_retry_respects_time_budget(self):
        """A transient failure with the wall-clock budget already spent must
        NOT retry — the record says why."""
        tasks = [TaskSpec(id="t1", title="one")]
        worker = _CountingWorker({"t1": [TimeoutError("slow timeout")]}, sleep=0.3)
        final = _run_graph(
            tasks,
            worker,
            budget=ExecutionBudget(time_budget_seconds=0.2),
            max_worker_retries=2,
        )
        assert worker.calls == ["t1"]
        record = (final.get("run_metadata") or {})["worker_failures"]["t1"]
        assert record["transient"] is True
        assert record["retries"] == 0
        assert record["retry_blocked_by"] == "time_budget"


def _synth_state(summaries: list[str], *, budget_reason: str | None, pending: int = 0):
    plan = PlanSpec(plan_id="p1", goal="triage the new findings", tasks=[])
    completed = [WorkerResult(task_id=f"t{i}", summary=s) for i, s in enumerate(summaries)]
    run_metadata: dict = {}
    if budget_reason:
        run_metadata["plan_status"] = "budget_exceeded"
        run_metadata["budget_exceeded_reason"] = budget_reason
    return {
        "plan": plan,
        "completed_tasks": completed,
        "artifacts": [],
        "pending_tasks": [TaskSpec(id=f"p{i}", title=f"pending {i}") for i in range(pending)],
        "run_metadata": run_metadata,
        "run_id": "run-test",
    }


_GET_LLM = "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm"


class TestSynthesizerBudgetHonesty:
    def test_budget_exhausted_with_no_summaries_short_circuits_without_llm(self):
        state = _synth_state([], budget_reason="max_worker_failures (2) reached — 2 failures", pending=3)
        with patch(_GET_LLM) as get_llm:
            result = llm_synthesizer(state)
            get_llm.assert_not_called()
        out = result["final_output"]
        assert out["goal_met"] is False
        assert out["budget_exceeded"] == "max_worker_failures (2) reached — 2 failures"
        assert "safety limit" in out["answer"]
        assert "3 planned task(s) were never executed" in out["answer"]
        assert result["run_metadata"]["synthesizer_short_circuited"] == "budget_exceeded"

    def test_budget_exhausted_with_summaries_forces_goal_not_met(self):
        """Even if the LLM claims GOAL_MET: yes, a truncated run cannot
        honestly report success — pending work was dropped."""
        state = _synth_state(
            ["Triaged 4 of 9 findings."],
            budget_reason="time_budget (300.0s) exceeded — 301.2s elapsed",
            pending=5,
        )
        fake_llm = MagicMock()
        fake_response = MagicMock()
        fake_response.content = "All findings triaged successfully.\nGOAL_MET: yes"
        fake_llm.invoke.return_value = fake_response
        with patch(_GET_LLM, return_value=fake_llm):
            result = llm_synthesizer(state)

        prompt_call = fake_llm.invoke.call_args.args[0]
        prompt_text = "\n".join(getattr(m, "content", "") for m in prompt_call)
        assert "stopped early" in prompt_text
        assert "time_budget" in prompt_text
        assert "5 planned task(s) were never executed" in prompt_text

        out = result["final_output"]
        assert out["goal_met"] is False
        assert result["run_metadata"]["goal_met"] is False
        assert out["budget_exceeded"] == "time_budget (300.0s) exceeded — 301.2s elapsed"

    def test_all_failures_plus_budget_reports_both(self):
        state = _synth_state(
            ["Agent stopped due to iteration limit"],
            budget_reason="max_iterations (50) reached",
        )
        with patch(_GET_LLM) as get_llm:
            result = llm_synthesizer(state)
            get_llm.assert_not_called()
        out = result["final_output"]
        assert out["goal_met"] is False
        assert out["budget_exceeded"] == "max_iterations (50) reached"
        assert "stopped early" in out["answer"]

    def test_no_budget_reason_keeps_llm_goal_met_verbatim(self):
        """No exhaustion → no override; the happy path is unchanged."""
        state = _synth_state(["Triaged all 9 findings."], budget_reason=None)
        fake_llm = MagicMock()
        fake_response = MagicMock()
        fake_response.content = "Done.\nGOAL_MET: yes"
        fake_llm.invoke.return_value = fake_response
        with patch(_GET_LLM, return_value=fake_llm):
            result = llm_synthesizer(state)
        assert result["final_output"]["goal_met"] is True
        assert result["final_output"]["budget_exceeded"] is None

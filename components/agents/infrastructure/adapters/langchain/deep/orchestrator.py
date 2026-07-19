"""
LangGraph-based orchestration scaffold for deep agents.

This stays lightweight: callers supply planner/worker functions and (optionally)
their own synthesizer and checkpointer. By default we use an in-memory
checkpointer so runs can be resumed during development.

SAFETY:
- The scheduler enforces an ExecutionBudget on every cycle (max iterations,
  max tasks, wall-clock time, cumulative worker failures).
- When any budget is exceeded the scheduler routes straight to the synthesizer
  instead of dispatching more work, and the synthesizer reports the exhaustion
  honestly instead of fabricating success.
- Worker exceptions are caught and recorded; they do NOT crash the graph.
  TRANSIENT failures (rate limits, timeouts, connection errors) get a bounded
  in-node retry (default 1, hard cap 2) that respects the run's time budget;
  deterministic failures never retry.
- Failure records live in ``run_metadata["worker_failures"]`` — a dict united
  across concurrent ``Send`` workers by the ``merge_run_metadata`` reducer.
  The cumulative failure count is DERIVED from those records (len minus the
  ``worker_failures_baseline`` watermark stamped at replan), never carried on
  a last-value int channel. The old ``worker_failure_count`` channel could
  never exceed 1 (each worker seeded from its empty ``Send`` payload) and two
  concurrently-failing workers raised ``InvalidUpdateError``.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterable

# langgraph 1.x: `Send` moved from langgraph.constants to langgraph.types;
# `interrupt` has lived there since 0.2 and is first-class in 1.x (resumed
# via `Command(resume=...)` — see runner.resume_plan).
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from langgraph.types import interrupt as _lg_interrupt

from components.agents.domain.value_objects.plan_schemas import (
    ExecutionBudget,
    PlanSpec,
    PlanState,
    TaskSpec,
)

from .checkpoints import default_checkpointer

logger = logging.getLogger(__name__)

PlannerFn = Callable[[PlanState], PlanSpec]
WorkerFn = Callable[[PlanState], dict]
SynthesizerFn = Callable[[PlanState], dict]


# ── Budget enforcement ────────────────────────────────────────────────


class BudgetExceeded(Exception):
    """Raised internally when any execution budget cap is hit."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# Absolute ceiling on per-task worker retries, regardless of agent_config.
# Retries multiply real LLM spend on a path that runs autonomously on beat
# cadence — the cap is a cost-control invariant, not a tunable.
MAX_WORKER_RETRIES_HARD_CAP = 2


def _derived_worker_failure_count(state: PlanState) -> int:
    """Cumulative worker failures for budget/replan decisions.

    Derived from ``run_metadata["worker_failures"]`` (one record per
    terminally-failed task, united across concurrent ``Send`` workers by the
    ``merge_run_metadata`` reducer) minus the ``worker_failures_baseline``
    watermark that ``replan_bookkeeping`` stamps — so a replan "resets" the
    count without deleting records (the reducer is additive-only; deletion by
    omission is unsupported by design).

    Falls back to the legacy ``worker_failure_count`` last-value channel when
    no records exist, so external writers and old checkpoints keep working.
    """
    run_metadata = state.get("run_metadata") or {}
    failures = run_metadata.get("worker_failures") or {}
    if failures:
        try:
            baseline = int(run_metadata.get("worker_failures_baseline") or 0)
        except (TypeError, ValueError):
            baseline = 0
        return max(0, len(failures) - baseline)
    try:
        return int(state.get("worker_failure_count") or 0)
    except (TypeError, ValueError):
        return 0


def _check_budget(state: PlanState) -> str | None:
    """Return a human-readable reason if the budget is exceeded, else None."""
    budget_dict = state.get("budget")
    if not budget_dict:
        return None

    budget = ExecutionBudget(**budget_dict) if isinstance(budget_dict, dict) else budget_dict

    iteration_count = state.get("iteration_count", 0)
    if iteration_count >= budget.max_iterations:
        return f"max_iterations ({budget.max_iterations}) reached"

    completed_count = len(state.get("completed_task_ids") or [])
    pending_count = len(state.get("pending_tasks") or [])
    if completed_count + pending_count >= budget.max_tasks:
        return f"max_tasks ({budget.max_tasks}) reached — {completed_count} completed, {pending_count} pending"

    start_time = state.get("start_time", 0)
    if start_time and (time.time() - start_time) >= budget.time_budget_seconds:
        elapsed = time.time() - start_time
        return f"time_budget ({budget.time_budget_seconds}s) exceeded — {elapsed:.1f}s elapsed"

    failure_count = _derived_worker_failure_count(state)
    if failure_count >= budget.max_worker_failures:
        return f"max_worker_failures ({budget.max_worker_failures}) reached — {failure_count} failures"

    return None


# ── Transient-failure classification (worker retry) ───────────────────
#
# Conservative by design: only failures that are provider/network-shaped
# (rate limits, timeouts, connection resets, transient 5xx) retry. A
# deterministic error — bad input, tool refusal, permission denial, a
# provider rejecting the request as invalid — will fail identically on
# every attempt; retrying it just burns LLM spend. When in doubt, do NOT
# retry.

# Exception class names (checked across the MRO so vendored subclasses of
# e.g. requests.ConnectionError match without importing every SDK).
_TRANSIENT_EXC_NAMES: frozenset[str] = frozenset(
    {
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionAbortedError",
        "BrokenPipeError",
    }
)

# Message substrings that only appear in transient provider/network errors.
# Deliberately phrase-level (no bare status-code numerals — "429" matches ids).
_TRANSIENT_MESSAGE_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate-limit",
    "rate_limit",
    "too many requests",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection error",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "overloaded",
)


def _is_transient_worker_error(exc: BaseException) -> bool:
    """True only for provider/network-shaped failures worth one more attempt.

    PermissionError is explicitly deterministic — the worker adapter raises it
    for disallowed agent types and it will never succeed on retry.
    """
    if isinstance(exc, PermissionError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    for klass in type(exc).__mro__:
        if klass.__name__ in _TRANSIENT_EXC_NAMES:
            return True
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS)


# ── Helpers ───────────────────────────────────────────────────────────


# AgentExecutor failure shapes the synthesizer must NOT paraphrase.
#
# When ReAct hits its iteration cap (or the worker times out), LangChain
# returns a stop string like "Agent stopped due to iteration or time
# limit before reaching a final answer." If we hand that to the LLM
# alongside the goal "list our top donors", it dutifully writes a
# plausible-sounding "Top Donors Report" — paraphrasing the failure as
# success. That's the 2026-05-08 hallucination shape. The guard short-
# circuits with an honest "I couldn't answer that" instead.
#
# Tool-calling (the post-PR-A default) makes iteration thrashing far
# rarer, but parse errors and explicit time-outs still surface here.
# Belt-and-suspenders: if any task came back as a known failure shape,
# treat it as a real failure rather than fodder for the LLM.
_AGENT_FAILURE_MARKERS: tuple[str, ...] = (
    "agent stopped due to iteration",
    "agent stopped due to time",
    "agent stopped due to max",
    "agent stopped due to iteration or time",
    "could not parse llm output",
    "failed to invoke agent",
    "max iterations reached",
)


def _is_agent_failure_summary(summary: str) -> bool:
    """True if *summary* matches an AgentExecutor "I gave up" stop string.

    These messages should never feed an LLM paraphrase pass — the LLM
    will confidently rewrite them as if the work succeeded. See the
    2026-05-08 chat reliability cascade RCA for the proven case.
    """
    if not summary:
        return False
    lowered = summary.lower()
    return any(marker in lowered for marker in _AGENT_FAILURE_MARKERS)


def _is_clarification(entry) -> bool:
    """True if *entry* is a clarify-short-circuit WorkerResult.

    The runner's clarify worker sets ``is_clarification=True`` on
    the WorkerResult when the planner emitted ``agent_type=clarify``
    for a vague goal. The synthesizer surfaces these summaries
    verbatim instead of paraphrasing them — the summary already IS
    the user-facing question. See ``build_clarify_worker`` and the
    2026-06-08 RCA.
    """
    if entry is None:
        return False
    value = getattr(entry, "is_clarification", None)
    if value is None and isinstance(entry, dict):
        value = entry.get("is_clarification")
    return bool(value)


def _format_honest_failure_answer(goal: str | None, summaries: list[str]) -> str:
    """Compose a user-visible failure message that does NOT hallucinate.

    Surfaces what was attempted and why it failed instead of asking the
    LLM to write a final answer from a stop string. The wording is
    deliberately plain — no "I apologize" boilerplate, no false
    optimism, no inventing detail the agent didn't produce.
    """
    goal_line = goal.strip() if isinstance(goal, str) else ""
    header = (
        f'I couldn\'t answer that. The agent for "{goal_line}" stopped '
        "before reaching a final answer — most likely because no tool on "
        "the routed agent matched the question. Try rephrasing, or ask "
        "what this agent can do."
        if goal_line
        else "I couldn't answer that. The agent stopped before reaching a "
        "final answer — most likely because no tool on the routed agent "
        "matched the question. Try rephrasing, or ask what this agent "
        "can do."
    )
    return header


def _format_budget_exhausted_answer(goal: str | None, reason: str, unfinished_count: int) -> str:
    """Honest user-visible message for a run stopped by budget exhaustion.

    Mirrors ``_format_honest_failure_answer``: plain wording, no false
    optimism, no inventing results the run never produced.
    """
    goal_line = goal.strip() if isinstance(goal, str) else ""
    subject = f'the run for "{goal_line}"' if goal_line else "the run"
    unfinished = f" {unfinished_count} planned task(s) were never executed." if unfinished_count else ""
    return (
        f"I couldn't complete that. Execution of {subject} was stopped "
        f"because it hit a safety limit ({reason}).{unfinished} "
        "No results were fabricated for the unfinished work."
    )


def llm_synthesizer(state: PlanState) -> dict:
    """LLM-backed final aggregator with goal/acceptance check.

    Builds a short summary from completed task summaries + artifacts and
    asks the LLM to (a) write a final answer and (b) flag whether the
    plan goal was met. On any failure we fall back to the no-op
    synthesizer so the run still completes.

    HONESTY GUARD: if every completed task came back as an AgentExecutor
    failure shape ("Agent stopped due to iteration limit", parse error,
    etc.), we DO NOT call the LLM — it would paraphrase the failure as a
    plausible-looking success. Instead we return a real failure message
    with ``goal_met=False``. Mixed runs (some real summaries, some
    failures) still go through the LLM, but the prompt is augmented so
    it doesn't paper over the failed tasks.
    """
    plan = state.get("plan")
    goal = getattr(plan, "goal", None) if plan else None
    completed = state.get("completed_tasks") or []
    artifacts = state.get("artifacts") or []
    run_metadata = dict(state.get("run_metadata") or {})
    # Budget honesty: when the scheduler stopped the run early, every
    # synthesizer path below must surface that fact instead of letting the
    # LLM narrate a truncated run as a finished one.
    budget_reason = run_metadata.get("budget_exceeded_reason")
    unfinished_count = len(state.get("pending_tasks") or [])

    summaries: list[str] = []
    clarification_summaries: list[str] = []
    for entry in completed:
        summary = getattr(entry, "summary", None) or (entry.get("summary") if isinstance(entry, dict) else None)
        if summary:
            summaries.append(str(summary))
            if _is_clarification(entry):
                clarification_summaries.append(str(summary))

    if not summaries:
        if budget_reason:
            # Nothing completed AND the budget tripped — there is no
            # material for an answer. Short-circuit with an honest
            # exhaustion message; calling the LLM here could only
            # fabricate.
            run_metadata["goal_met"] = False
            run_metadata["synthesizer_short_circuited"] = "budget_exceeded"
            logger.warning(
                "deep_agent.synthesizer_budget_guard run_id=%s goal=%s reason=%s "
                "no completed summaries; returning honest budget-exhaustion answer",
                state.get("run_id"),
                goal,
                budget_reason,
            )
            return {
                "final_output": {
                    "answer": _format_budget_exhausted_answer(goal, budget_reason, unfinished_count),
                    "completed_tasks": completed,
                    "artifacts": artifacts,
                    "run_metadata": run_metadata,
                    "goal_met": False,
                    "budget_exceeded": budget_reason,
                },
                "run_metadata": run_metadata,
            }
        return _no_op_synthesizer(state)

    # Clarification short-circuit: when the planner emitted a
    # ``agent_type=clarify`` task for a vague goal, its WorkerResult
    # carries the clarifying question as ``summary``. Surface it
    # verbatim — no LLM round-trip, no honesty-guard failure message.
    # The goal isn't "met" (we're asking the user a question), but the
    # answer the user sees IS useful, not a wall of "I couldn't answer
    # that". The clarification path takes precedence over the
    # all-failures guard so a clarify task that runs alongside a
    # failed specialist still surfaces the clarifying question instead
    # of the failure boilerplate. (2026-06-08 RCA)
    if clarification_summaries and len(clarification_summaries) == len(summaries):
        run_metadata["goal_met"] = False
        run_metadata["needs_clarification"] = True
        run_metadata["synthesizer_short_circuited"] = "clarification"
        logger.info(
            "deep_agent.synthesizer_clarification run_id=%s goal=%s clarifications=%d "
            "surfacing planner's clarifying question directly",
            state.get("run_id"),
            goal,
            len(clarification_summaries),
        )
        answer = "\n\n".join(clarification_summaries).strip()
        return {
            "final_output": {
                "answer": answer,
                "completed_tasks": completed,
                "artifacts": artifacts,
                "run_metadata": run_metadata,
                "goal_met": False,
                "needs_clarification": True,
            },
            "run_metadata": run_metadata,
        }

    # Honesty guard: if EVERY summary is an AgentExecutor stop-string,
    # short-circuit. Calling the LLM here is what produced the
    # 2026-05-08 hallucination — it confidently paraphrased "Agent
    # stopped due to iteration limit" into a fabricated "4 tasks"
    # response.
    failure_markers = [_is_agent_failure_summary(s) for s in summaries]
    if all(failure_markers):
        run_metadata["goal_met"] = False
        run_metadata["synthesizer_short_circuited"] = "all_tasks_failed"
        logger.warning(
            "deep_agent.synthesizer_honesty_guard run_id=%s goal=%s summaries=%d "
            "every task hit an AgentExecutor failure shape; returning "
            "honest failure instead of LLM paraphrase",
            state.get("run_id"),
            goal,
            len(summaries),
        )
        answer = _format_honest_failure_answer(goal, summaries)
        if budget_reason:
            answer = f"{answer}\n\nExecution was also stopped early: {budget_reason}."
        return {
            "final_output": {
                "answer": answer,
                "completed_tasks": completed,
                "artifacts": artifacts,
                "run_metadata": run_metadata,
                "goal_met": False,
                "budget_exceeded": budget_reason or None,
            },
            "run_metadata": run_metadata,
        }

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from components.knowledge.infrastructure.factories.llms.factory import LLMFactory

        llm = LLMFactory.get_llm()
        # Tag failed task summaries inline so the LLM cannot rewrite
        # them as success. A mixed run (e.g. one tool returned data, one
        # hit the iteration cap) must surface BOTH outcomes — a partial
        # answer plus an honest "task X couldn't be completed" line.
        annotated: list[str] = []
        any_failed = False
        for raw in summaries[:25]:
            if _is_agent_failure_summary(raw):
                any_failed = True
                annotated.append(f"[FAILED — DID NOT PRODUCE DATA] {raw}")
            else:
                annotated.append(raw)
        joined = "\n- ".join(annotated)

        failure_caveat = ""
        if any_failed:
            failure_caveat = (
                "\n\nIMPORTANT: One or more tasks above are tagged "
                "[FAILED — DID NOT PRODUCE DATA]. Do NOT invent results "
                "for those tasks. State plainly that they couldn't be "
                "completed and answer only from the tasks that succeeded."
            )
        if budget_reason:
            failure_caveat += (
                f"\n\nIMPORTANT: Execution was stopped early because it hit "
                f"a safety limit ({budget_reason})."
                + (f" {unfinished_count} planned task(s) were never executed." if unfinished_count else "")
                + " State this plainly. Do NOT claim the goal was fully met "
                "and do NOT invent results for work that never ran."
            )

        prompt = (
            f"Goal: {goal or '(unspecified)'}\n\n"
            f"Completed task summaries:\n- {joined}\n\n"
            f"Artifacts produced: {len(artifacts)}\n\n"
            "Write a concise final answer for the user (2-6 sentences). "
            "Then on a new line write `GOAL_MET: yes` or `GOAL_MET: no` "
            "and, if no, `REPLAN_REQUESTED: yes` so the orchestrator can "
            "decide whether to replan."
            f"{failure_caveat}"
        )
        response = llm.invoke(
            [
                SystemMessage(content="You are a deep-agent synthesizer."),
                HumanMessage(content=prompt),
            ]
        )
        text = (getattr(response, "content", None) or str(response)).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("llm_synthesizer failed, falling back to no-op: %s", exc)
        return _no_op_synthesizer(state)

    lower = text.lower()
    goal_met = "goal_met: yes" in lower
    replan_requested = "replan_requested: yes" in lower
    if budget_reason:
        # A run the scheduler cut short cannot honestly claim the goal was
        # met — planned work was dropped. Override an over-optimistic LLM.
        goal_met = False
    if replan_requested:
        run_metadata["replan_requested"] = True
    run_metadata["goal_met"] = goal_met

    return {
        "final_output": {
            "answer": text,
            "completed_tasks": completed,
            "artifacts": artifacts,
            "run_metadata": run_metadata,
            "goal_met": goal_met,
            "budget_exceeded": budget_reason or None,
        },
        "run_metadata": run_metadata,
    }


def _no_op_synthesizer(state: PlanState) -> dict:
    """Fallback synthesizer that just returns accumulated tasks/artifacts."""
    budget_reason = state.get("run_metadata", {}).get("budget_exceeded_reason")
    return {
        "final_output": {
            "completed_tasks": state.get("completed_tasks", []),
            "artifacts": state.get("artifacts", []),
            "run_metadata": state.get("run_metadata", {}),
            "budget_exceeded": budget_reason or None,
        }
    }


def _task_id(task: TaskSpec) -> str:
    return str(task.id or "").strip()


def _coerce_dep_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    return []


def _extract_dependencies(task: TaskSpec) -> set[str]:
    deps: set[str] = set()
    if task.parent_task_id:
        deps.add(str(task.parent_task_id).strip())
    deps.update(_coerce_dep_list(task.depends_on))
    metadata = task.metadata or {}
    deps.update(_coerce_dep_list(metadata.get("depends_on") or metadata.get("depends_on_ids")))
    return {dep for dep in deps if dep}


def _resolve_ready_tasks(pending: Iterable[TaskSpec], completed_ids: set[str]) -> tuple[list[TaskSpec], list[TaskSpec]]:
    ready: list[TaskSpec] = []
    blocked: list[TaskSpec] = []
    for task in pending:
        task_id = _task_id(task)
        if task_id and task_id in completed_ids:
            continue
        deps = _extract_dependencies(task)
        if deps and not deps.issubset(completed_ids):
            blocked.append(task)
        else:
            ready.append(task)
    return ready, blocked


# ── Graph builder ─────────────────────────────────────────────────────


def build_orchestrator(
    planner_fn: PlannerFn,
    worker_fn: WorkerFn,
    synthesizer_fn: SynthesizerFn | None = None,
    checkpointer=None,
    budget: ExecutionBudget | None = None,
    cancellation_token=None,
    approval_required: bool = False,
    max_replans: int = 1,
    max_worker_retries: int = 1,
    retry_backoff_seconds: float = 1.0,
) -> StateGraph:
    """
    Compile a LangGraph app with planner, worker fan-out, and synthesizer nodes.

    Args:
        planner_fn: Returns a PlanSpec; its tasks become the initial ready queue.
        worker_fn: Returns state deltas (completed_tasks/artifacts) per task.
        synthesizer_fn: Optional final aggregation; receives full state.
        checkpointer: LangGraph checkpointer (default: in-memory).
        budget: ExecutionBudget caps. If None, uses safe defaults.
        max_worker_retries: per-task retries for TRANSIENT worker failures
            (see ``_is_transient_worker_error``). Clamped to
            ``0..MAX_WORKER_RETRIES_HARD_CAP``; deterministic failures never
            retry. Retries respect the run's remaining time budget.
        retry_backoff_seconds: base linear backoff between retry attempts
            (attempt N sleeps N * base, capped at the remaining time budget).
    """
    if planner_fn is None or worker_fn is None:
        raise ValueError("planner_fn and worker_fn are required.")

    effective_budget = budget or ExecutionBudget()
    synth = synthesizer_fn or _no_op_synthesizer
    saver = checkpointer or default_checkpointer()
    try:
        effective_max_retries = max(0, min(int(max_worker_retries), MAX_WORKER_RETRIES_HARD_CAP))
    except (TypeError, ValueError):
        effective_max_retries = 1

    # Workers receive ONLY their ``Send`` payload ({"task": ...}) as input
    # state — no start_time, no budget. The retry loop still must respect
    # the run's wall-clock budget, so the planner records the run start in
    # this closure-scoped holder (one graph instance per run; a re-invoke
    # simply re-stamps it at the planner).
    run_started_at: dict[str, float | None] = {"ts": None}

    def _remaining_time_budget() -> float | None:
        started = run_started_at.get("ts")
        if not started:
            return None
        return effective_budget.time_budget_seconds - (time.time() - started)

    builder = StateGraph(PlanState)

    def planner_node(state: PlanState) -> PlanState:
        plan = planner_fn(state)
        pending_tasks: list[TaskSpec] = list(plan.tasks or [])
        for task in pending_tasks:
            if not task.id:
                task.id = str(uuid.uuid4())
        now = time.time()
        # Preserve the ORIGINAL run start across replans — a replanned run
        # must not get a fresh wall-clock budget.
        start_time = state.get("start_time") or now
        run_started_at["ts"] = start_time
        return {
            "plan": plan,
            "pending_tasks": pending_tasks,
            "completed_task_ids": [],
            "iteration_count": 0,
            "worker_failure_count": 0,
            "start_time": start_time,
            "budget": effective_budget.model_dump(),
        }

    def scheduler_node(state: PlanState) -> PlanState:
        # Check cancellation FIRST — before any work
        if cancellation_token and cancellation_token.is_cancelled:
            run_metadata = dict(state.get("run_metadata") or {})
            run_metadata["plan_status"] = "cancelled"
            run_metadata["cancel_reason"] = cancellation_token.reason
            logger.info("deep_agent.cancelled run_id=%s reason=%s", state.get("run_id"), cancellation_token.reason)
            return {
                "pending_tasks": list(state.get("pending_tasks") or []),
                "ready_tasks": [],
                "run_metadata": run_metadata,
            }

        # Increment iteration counter
        iteration_count = (state.get("iteration_count") or 0) + 1

        # If a prior node (e.g. approval rejection) marked the run as
        # rejected, force an empty ready queue so we route straight to
        # the synthesizer without re-scheduling tasks from the plan.
        existing_metadata = state.get("run_metadata") or {}
        if existing_metadata.get("plan_status") == "rejected":
            return {
                "pending_tasks": [],
                "ready_tasks": [],
                "run_metadata": existing_metadata,
                "iteration_count": iteration_count,
            }

        plan = state.get("plan")
        pending = list(state.get("pending_tasks") or (list(plan.tasks or []) if plan else []))
        completed_ids = set(state.get("completed_task_ids") or [])
        pending = [task for task in pending if _task_id(task) not in completed_ids]
        ready, blocked = _resolve_ready_tasks(pending, completed_ids)

        run_metadata = dict(state.get("run_metadata") or {})
        run_metadata["iteration_count"] = iteration_count

        # Check budget BEFORE dispatching more work
        budget_reason = _check_budget({**state, "iteration_count": iteration_count})
        if budget_reason:
            logger.warning(
                "deep_agent.budget_exceeded run_id=%s reason=%s iterations=%d",
                state.get("run_id"),
                budget_reason,
                iteration_count,
            )
            run_metadata["plan_status"] = "budget_exceeded"
            run_metadata["budget_exceeded_reason"] = budget_reason
            return {
                "pending_tasks": pending,
                "ready_tasks": [],  # Force route to synthesizer
                "run_metadata": run_metadata,
                "iteration_count": iteration_count,
            }

        if pending and not ready:
            run_metadata["plan_status"] = "blocked"
            run_metadata["blocked_task_ids"] = [_task_id(task) for task in blocked if _task_id(task)]
        elif not pending:
            run_metadata["plan_status"] = "completed"
        else:
            run_metadata["plan_status"] = "running"

        return {
            "pending_tasks": pending,
            "ready_tasks": ready,
            "run_metadata": run_metadata,
            "iteration_count": iteration_count,
        }

    def dispatch_ready_tasks(state: PlanState):
        ready = state.get("ready_tasks") or []
        if not ready:
            return "synthesizer"
        return [Send("worker", {"task": task}) for task in ready]

    def worker_node(state: PlanState) -> PlanState:
        task = state.get("task")
        task_id_str = _task_id(task) if task else ""
        retries_used = 0

        while True:
            try:
                result = worker_fn(state)
                break
            except Exception as exc:
                transient = _is_transient_worker_error(exc)
                retry_blocked_by: str | None = None
                if transient and retries_used < effective_max_retries:
                    remaining = _remaining_time_budget()
                    if remaining is None or remaining > 0:
                        retries_used += 1
                        logger.warning(
                            "deep_agent.worker_retry task_id=%s attempt=%d/%d error_type=%s error=%s",
                            task_id_str,
                            retries_used,
                            effective_max_retries,
                            type(exc).__name__,
                            exc,
                        )
                        if retry_backoff_seconds > 0:
                            delay = retry_backoff_seconds * retries_used
                            if remaining is not None:
                                delay = min(delay, max(remaining, 0.0))
                            if delay > 0:
                                time.sleep(delay)
                        continue
                    retry_blocked_by = "time_budget"

                # Terminal failure — record it in run_metadata under the
                # reducer-united ``worker_failures`` key. Concurrent Send
                # workers merge instead of colliding (the old last-value
                # ``worker_failure_count`` int raised InvalidUpdateError
                # here), and the budget/replan checks derive the count
                # from these records.
                logger.exception(
                    "deep_agent.worker_failed task_id=%s transient=%s retries_used=%d error=%s",
                    task_id_str,
                    transient,
                    retries_used,
                    exc,
                )
                failure_record: dict = {
                    "task_id": task_id_str or None,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "transient": transient,
                    "retries": retries_used,
                    "failed_at": time.time(),
                }
                if retry_blocked_by:
                    failure_record["retry_blocked_by"] = retry_blocked_by
                failure_key = task_id_str or f"unknown-{uuid.uuid4().hex[:8]}"
                run_metadata_delta: dict = {"worker_failures": {failure_key: failure_record}}
                if task_id_str:
                    # Legacy per-task error key — kept for existing consumers.
                    run_metadata_delta[f"worker_error_{task_id_str}"] = str(exc)
                if retries_used:
                    run_metadata_delta["worker_retries"] = {failure_key: retries_used}
                return {
                    "completed_task_ids": [task_id_str] if task_id_str else [],
                    "run_metadata": run_metadata_delta,
                }

        if task_id_str:
            result.setdefault("completed_task_ids", []).append(task_id_str)
        if retries_used:
            # Success after retry — make it visible in run telemetry.
            run_metadata = dict(result.get("run_metadata") or {})
            retries_map = dict(run_metadata.get("worker_retries") or {})
            retries_map[task_id_str or "unknown"] = retries_used
            run_metadata["worker_retries"] = retries_map
            result["run_metadata"] = run_metadata
        return result

    def synthesizer_node(state: PlanState) -> PlanState:
        return synth(state)

    def approval_node(state: PlanState) -> PlanState:
        """HITL gate. Pauses the graph via langgraph `interrupt` until a
        caller resumes with `Command(resume={"approved": True/False})`.
        On langgraph < 0.2 the import fallback no-ops and the gate is
        bypassed (logged).
        """
        plan = state.get("plan")
        payload = {
            "plan_id": getattr(plan, "plan_id", None) if plan else None,
            "task_count": len(getattr(plan, "tasks", []) or []) if plan else 0,
            "goal": getattr(plan, "goal", None) if plan else None,
        }
        decision = _lg_interrupt(payload) or {}
        run_metadata = dict(state.get("run_metadata") or {})
        run_metadata["approval"] = decision
        if isinstance(decision, dict) and decision.get("approved") is False:
            run_metadata["plan_status"] = "rejected"
            return {"run_metadata": run_metadata, "ready_tasks": [], "pending_tasks": []}
        return {"run_metadata": run_metadata}

    def replan_check(state: PlanState) -> str:
        """Conditional edge after synthesizer: replan once if workers
        failed too often or a worker explicitly requested a replan."""
        run_metadata = state.get("run_metadata") or {}
        replans_done = int(run_metadata.get("replans_done", 0))
        if replans_done >= max_replans:
            return "end"
        failure_count = _derived_worker_failure_count(state)
        replan_requested = bool(run_metadata.get("replan_requested"))
        if failure_count > 0 and (failure_count >= 2 or replan_requested):
            return "planner"
        return "end"

    def replan_bookkeeping(state: PlanState) -> PlanState:
        run_metadata = dict(state.get("run_metadata") or {})
        run_metadata["replans_done"] = int(run_metadata.get("replans_done", 0)) + 1
        # Failure-count "reset": the merge reducer is additive-only, so
        # instead of deleting ``worker_failures`` records we stamp a
        # baseline watermark. ``_derived_worker_failure_count`` counts only
        # records above it, so pre-replan failures no longer trip the
        # budget while the full failure history stays in telemetry.
        run_metadata["worker_failures_baseline"] = len(run_metadata.get("worker_failures") or {})
        return {"run_metadata": run_metadata, "worker_failure_count": 0}

    builder.add_node("planner", planner_node)
    if approval_required:
        builder.add_node("approval", approval_node)
    builder.add_node("scheduler", scheduler_node)
    builder.add_node("worker", worker_node)
    builder.add_node("synthesizer", synthesizer_node)
    builder.add_node("replan_bookkeeping", replan_bookkeeping)

    builder.add_edge(START, "planner")
    if approval_required:
        builder.add_edge("planner", "approval")
        builder.add_edge("approval", "scheduler")
    else:
        builder.add_edge("planner", "scheduler")
    builder.add_conditional_edges("scheduler", dispatch_ready_tasks, ["worker", "synthesizer"])
    builder.add_edge("worker", "scheduler")
    builder.add_conditional_edges(
        "synthesizer",
        replan_check,
        {"planner": "replan_bookkeeping", "end": END},
    )
    builder.add_edge("replan_bookkeeping", "planner")

    return builder.compile(checkpointer=saver)

"""
LangGraph-based orchestration scaffold for deep agents.

This stays lightweight: callers supply planner/worker functions and (optionally)
their own synthesizer and checkpointer. By default we use an in-memory
checkpointer so runs can be resumed during development.

SAFETY:
- The scheduler enforces an ExecutionBudget on every cycle (max iterations,
  max tasks, wall-clock time, cumulative worker failures).
- When any budget is exceeded the scheduler routes straight to the synthesizer
  instead of dispatching more work.
- Worker exceptions are caught and counted; they do NOT crash the graph.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterable

from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

# `interrupt` is langgraph >= 0.2. Older installs raise ImportError; we
# fall back to a no-op so the import path stays safe but HITL gates are
# only effective on supported versions.
try:
    from langgraph.types import interrupt as _lg_interrupt  # type: ignore
except Exception:  # pragma: no cover - older langgraph
    def _lg_interrupt(payload):  # type: ignore
        return payload

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

    failure_count = state.get("worker_failure_count", 0)
    if failure_count >= budget.max_worker_failures:
        return f"max_worker_failures ({budget.max_worker_failures}) reached"

    return None


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
        f"I couldn't answer that. The agent for \"{goal_line}\" stopped "
        "before reaching a final answer — most likely because no tool on "
        "the routed agent matched the question. Try rephrasing, or ask "
        "what this agent can do."
        if goal_line
        else
        "I couldn't answer that. The agent stopped before reaching a "
        "final answer — most likely because no tool on the routed agent "
        "matched the question. Try rephrasing, or ask what this agent "
        "can do."
    )
    return header


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

    summaries: list[str] = []
    clarification_summaries: list[str] = []
    for entry in completed:
        summary = getattr(entry, "summary", None) or (entry.get("summary") if isinstance(entry, dict) else None)
        if summary:
            summaries.append(str(summary))
            if _is_clarification(entry):
                clarification_summaries.append(str(summary))

    if not summaries:
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
        return {
            "final_output": {
                "answer": _format_honest_failure_answer(goal, summaries),
                "completed_tasks": completed,
                "artifacts": artifacts,
                "run_metadata": run_metadata,
                "goal_met": False,
            },
            "run_metadata": run_metadata,
        }

    try:
        from langchain.schema import HumanMessage, SystemMessage
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
        response = llm.invoke([
            SystemMessage(content="You are a deep-agent synthesizer."),
            HumanMessage(content=prompt),
        ])
        text = (getattr(response, "content", None) or str(response)).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("llm_synthesizer failed, falling back to no-op: %s", exc)
        return _no_op_synthesizer(state)

    lower = text.lower()
    goal_met = "goal_met: yes" in lower
    replan_requested = "replan_requested: yes" in lower
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
) -> StateGraph:
    """
    Compile a LangGraph app with planner, worker fan-out, and synthesizer nodes.

    Args:
        planner_fn: Returns a PlanSpec; its tasks become the initial ready queue.
        worker_fn: Returns state deltas (completed_tasks/artifacts) per task.
        synthesizer_fn: Optional final aggregation; receives full state.
        checkpointer: LangGraph checkpointer (default: in-memory).
        budget: ExecutionBudget caps. If None, uses safe defaults.
    """
    if planner_fn is None or worker_fn is None:
        raise ValueError("planner_fn and worker_fn are required.")

    effective_budget = budget or ExecutionBudget()
    synth = synthesizer_fn or _no_op_synthesizer
    saver = checkpointer or default_checkpointer()

    builder = StateGraph(PlanState)

    def planner_node(state: PlanState) -> PlanState:
        plan = planner_fn(state)
        pending_tasks: list[TaskSpec] = list(plan.tasks or [])
        for task in pending_tasks:
            if not task.id:
                task.id = str(uuid.uuid4())
        return {
            "plan": plan,
            "pending_tasks": pending_tasks,
            "completed_task_ids": [],
            "iteration_count": 0,
            "worker_failure_count": 0,
            "start_time": time.time(),
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

        try:
            result = worker_fn(state)
        except Exception as exc:
            logger.exception(
                "deep_agent.worker_failed task_id=%s error=%s",
                task_id_str,
                exc,
            )
            failure_count = (state.get("worker_failure_count") or 0) + 1
            result = {
                "completed_task_ids": [task_id_str] if task_id_str else [],
                "worker_failure_count": failure_count,
                "run_metadata": {
                    **(state.get("run_metadata") or {}),
                    f"worker_error_{task_id_str}": str(exc),
                },
            }
            return result

        if task_id_str:
            result.setdefault("completed_task_ids", []).append(task_id_str)
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
        failure_count = state.get("worker_failure_count") or 0
        replan_requested = bool(run_metadata.get("replan_requested"))
        if failure_count > 0 and (failure_count >= 2 or replan_requested):
            return "planner"
        return "end"

    def replan_bookkeeping(state: PlanState) -> PlanState:
        run_metadata = dict(state.get("run_metadata") or {})
        run_metadata["replans_done"] = int(run_metadata.get("replans_done", 0)) + 1
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

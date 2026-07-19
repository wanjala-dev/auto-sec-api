"""
Convenience runner for executing a PlanSpec with an existing agent as worker.

This is a light wrapper that:
1) Builds an agent-backed worker via `build_worker_from_agent`.
2) Optionally syncs each TaskSpec into the kanban board (idempotent).
3) Invokes the LangGraph orchestrator once (no retries/budgeting yet).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from components.agents.domain.services.deep.utils import to_serializable
from components.agents.domain.value_objects.plan_schemas import (
    CLARIFY_AGENT_TYPE,
    PlanSpec,
    PlanState,
    TaskSpec,
    WorkerResult,
)
from components.agents.infrastructure.gateways.deep.artifacts import store_artifact
from components.agents.infrastructure.gateways.deep.kanban_sync_service import upsert_task_from_spec
from components.agents.infrastructure.gateways.deep.logging import log_deep_event

from .adapters import build_worker_from_agent
from .orchestrator import build_orchestrator, llm_synthesizer


def build_clarify_worker(
    *,
    thread_id: str | None = None,
) -> callable:
    """Return a worker that handles ``agent_type=clarify`` tasks.

    Clarifying tasks are emitted by the planner when the user's goal is
    too vague to route to any specialist (e.g. "tldr", "summary",
    "how are we doing?"). The task carries the clarifying question in
    its ``description`` (preferred) or ``title``; this worker surfaces
    that text as the ``WorkerResult.summary`` and marks the result with
    ``is_clarification=True`` so the synthesizer can skip its LLM
    paraphrase pass and show the question to the user verbatim.

    No agent dispatch, no LangChain AgentExecutor, no LLM call. This is
    the load-bearing piece of the 2026-06-08 fix — see
    ``docs/rca/2026-06-08-clarify-task-thrash.md``. Before it existed,
    clarifying tasks were dispatched to ``workspace_agent``, which
    thrashed through ~17 LLM rounds before the honesty guard fired.
    """

    def worker(state: PlanState) -> PlanState:
        task: TaskSpec | None = state.get("task") if state else None
        if not task:
            return {}
        question = (task.description or task.title or "").strip()
        log_deep_event(
            thread_id,
            "clarify_short_circuit",
            status="completed",
            agent_type=CLARIFY_AGENT_TYPE,
            payload={"task_id": task.id, "question": question},
        )
        result = WorkerResult(
            task_id=task.id,
            summary=question or "Could you clarify what you'd like?",
            artifact_refs=[],
            risks=[],
            next_inputs={},
            is_clarification=True,
        )
        return {"completed_tasks": [result], "artifacts": []}

    return worker


DEFAULT_MEMORY_LIMITS = {
    "max_messages": 40,
    "max_message_chars": 2000,
    "max_total_chars": 20000,
}


def _coerce_limit(value: Any) -> int | None:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def _resolve_memory_limits(agent_config: dict[str, Any] | None) -> dict[str, int]:
    limits: dict[str, int] = {}
    if agent_config:
        explicit = agent_config.get("run_memory_limits") or agent_config.get("memory_limits")
        if isinstance(explicit, dict):
            for key in ("max_messages", "max_message_chars", "max_total_chars"):
                if key in explicit:
                    coerced = _coerce_limit(explicit.get(key))
                    if coerced is not None:
                        limits[key] = coerced
        mapped = {
            "max_messages": agent_config.get("memory_max_messages"),
            "max_message_chars": agent_config.get("memory_max_message_chars"),
            "max_total_chars": agent_config.get("memory_max_total_chars"),
        }
        for key, value in mapped.items():
            coerced = _coerce_limit(value)
            if coerced is not None:
                limits[key] = coerced

    for key, value in DEFAULT_MEMORY_LIMITS.items():
        limits.setdefault(key, value)
    return limits


def _coerce_list(value: Any) -> list[str] | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return None


def execute_plan_once(
    plan: PlanSpec,
    *,
    agent_type: str,
    user_id: str,
    workspace_id: str,
    agent_config: dict | None = None,
    thread_id: str | None = None,
    sync_to_kanban: bool = True,
    max_iterations: int = 50,
    time_budget_seconds: float = 300.0,
    max_worker_failures: int = 10,
    max_replans: int = 1,
    use_llm_synthesizer: bool = True,
    deep_run_context: Any | None = None,
    force_worker_agent_type: str | None = None,
    max_reflections: int = 0,
) -> PlanState:
    """
    Execute a PlanSpec using a single agent type as the worker.

    Args:
        plan: structured plan with tasks.
        agent_type: agent slug to handle each task (e.g., "task_agent").
        user_id: human owner of the agent.
        workspace_id: workspace context for the agent.
        agent_config: optional config for the agent.
        thread_id: optional run id for the checkpointer; auto-generated if absent.
        sync_to_kanban: if True, each TaskSpec is upserted into the kanban board.
        force_worker_agent_type: when set, EVERY non-clarify task is dispatched to
            this agent regardless of the ``agent_type`` the planner put on the
            task. This is the deterministic-handoff equivalent of LangGraph's
            ``Command(goto=...)``: when a caller already KNOWS the specialist
            (e.g. a detector delegating to its paired agent), the planner must
            not re-route by keyword. Without it the planner sent triage work to
            ``log_watch_agent`` (which lacks the tools) and it fabricated success
            — the §5.13 mis-route-and-hallucinate failure. ``None`` = unchanged
            per-task routing (the interactive default).
    """

    def planner_fn(_: PlanState) -> PlanSpec:
        return plan

    run_thread = thread_id or plan.plan_id
    memory_limits = _resolve_memory_limits(agent_config)
    department_id = None
    if isinstance(agent_config, dict):
        department_id = agent_config.get("department_id") or agent_config.get("team_id")
    if not department_id:
        for task in plan.tasks:
            if task.team_id:
                department_id = task.team_id
                break
    if not department_id:
        department_id = (plan.metadata or {}).get("department_id") if isinstance(plan.metadata, dict) else None
    allowed_agents = None
    allowed_tools = None
    blocked_tools = None
    if isinstance(agent_config, dict):
        allowed_agents = _coerce_list(agent_config.get("allowed_agents"))
        allowed_tools = _coerce_list(agent_config.get("allowed_tools"))
        blocked_tools = _coerce_list(agent_config.get("blocked_tools"))
    if not allowed_agents and isinstance(plan.metadata, dict):
        allowed_agents = _coerce_list(plan.metadata.get("allowed_agents"))
    if not allowed_tools and isinstance(plan.metadata, dict):
        allowed_tools = _coerce_list(plan.metadata.get("allowed_tools"))
    if not blocked_tools and isinstance(plan.metadata, dict):
        blocked_tools = _coerce_list(plan.metadata.get("blocked_tools"))

    # ``run_context`` is JSON-serialised by LangGraph on every checkpoint
    # write, so it MUST contain only round-trippable values. The live
    # ``DeepRunContext`` (which holds an observability adapter object)
    # would crash the checkpoint with TypeError. Passed separately to
    # ``build_worker_from_agent`` as a closure kwarg below.
    run_context = {
        "run_id": run_thread,
        "plan_id": plan.plan_id,
        "workspace_id": workspace_id,
        "principal_id": user_id,
        "conversation_id": str(uuid.uuid4()),
        "memory_limits": memory_limits,
        "department_id": department_id,
        "allowed_agents": allowed_agents,
        "allowed_tools": allowed_tools,
        "blocked_tools": blocked_tools,
    }

    approval_required = False
    if isinstance(agent_config, dict):
        approval_required = bool(agent_config.get("approval_required"))
        if agent_config.get("approval_policy") in {"manual", "human", "approval"}:
            approval_required = True

    for task in plan.tasks:
        if not task.id:
            task.id = str(uuid.uuid4())
        if not task.workspace_id:
            task.workspace_id = workspace_id
        if not task.team_id and department_id:
            task.team_id = department_id

    from infrastructure.persistence.ai.agents.models import DeepRun  # local import to avoid circular

    DeepRun.objects.update_or_create(
        thread_id=run_thread,
        defaults={
            "plan_id": plan.plan_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "status": DeepRun.STATUS_RUNNING,
        },
    )
    log_deep_event(run_thread, "run_started", status=DeepRun.STATUS_RUNNING, payload={"plan_id": plan.plan_id})

    # NOTE: HITL is now handled inside the graph by the `approval` node
    # using `langgraph.interrupt()` (see deep/orchestrator.py). The graph
    # pauses on the checkpoint and is resumed by re-invoking with
    # `Command(resume={"approved": True})` from the approval API. The
    # legacy pre-run "early return" gate has been removed.

    if sync_to_kanban:
        for task in plan.tasks:
            # Don't sync clarifying meta-tasks to the kanban — they're
            # ask-the-user prompts that surface as the chat answer, not
            # work the user owns. Cluttering the AI-team board with
            # them would confuse the activity surface. (2026-06-08)
            if (task.agent_type or "").strip() == CLARIFY_AGENT_TYPE:
                continue
            try:
                created_task = upsert_task_from_spec(task, created_by_id=user_id)
                if created_task and not task.id:
                    task.id = str(created_task.id)
            except Exception:
                pass

    sync_in_worker = False

    # Per-task specialist routing.
    #
    # Each TaskSpec the planner emits carries an ``agent_type`` field
    # picked from the registered agent catalog (budget_agent for
    # budget tasks, sponsorship_agent for sponsor tasks, etc.). The
    # runner builds a worker per agent_type lazily — a chat that only
    # touches budgets builds one budget_agent worker, a chat that
    # spans budgets + sponsorship builds two. Falls back to the
    # chat's default ``agent_type`` (the use case's ``command.agent_type``,
    # typically ``workspace_agent``) when a task has no
    # ``agent_type`` set, so older planners and back-compat callers
    # keep working unchanged.
    #
    # This is the load-bearing fix for the 2026-05-08 hallucination
    # where "how many budgets do we have?" was dispatched to
    # ``workspace_agent`` (no budget tools) and the agent fabricated
    # "0" from membership metadata. With per-task routing the task
    # lands on ``budget_agent`` whose ``list_budgets`` tool returns
    # the real count.
    _worker_cache: dict[str, Any] = {}

    def _resolve_worker(task_agent_type: str | None):
        # Normalise: empty string / None → fall back to chat default.
        resolved = (task_agent_type or "").strip() or agent_type
        if resolved not in _worker_cache:
            if resolved == CLARIFY_AGENT_TYPE:
                # Clarifying tasks bypass agent dispatch entirely — the
                # task.description IS the answer. See
                # ``build_clarify_worker`` for the rationale; before
                # this sentinel existed, the planner routed
                # clarifications to ``workspace_agent``, which thrashed
                # through ~17 LLM rounds chasing a tool that doesn't
                # exist. (2026-06-08 RCA)
                _worker_cache[resolved] = build_clarify_worker(
                    thread_id=run_thread,
                )
            else:
                _worker_cache[resolved] = build_worker_from_agent(
                    agent_type=resolved,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    config=agent_config or {},
                    run_context=run_context,
                    deep_run_context=deep_run_context,
                )
        return _worker_cache[resolved]

    # Pre-build the default worker so cold-start latency is paid once
    # at runner setup instead of on first task dispatch (matches the
    # pre-fix behaviour exactly when no task carries an explicit
    # agent_type).
    _resolve_worker(agent_type)

    def worker_fn(state: PlanState) -> PlanState:
        task: TaskSpec | None = state.get("task")
        # Deterministic handoff: a caller-pinned worker overrides whatever the
        # planner routed the task to (clarify tasks still bypass to their
        # sentinel worker). Mirrors LangGraph's Command(goto=...) for known
        # targets — see force_worker_agent_type in the docstring.
        task_agent_type = getattr(task, "agent_type", None)
        if force_worker_agent_type and (task_agent_type or "").strip() != CLARIFY_AGENT_TYPE:
            task_agent_type = force_worker_agent_type
        worker = _resolve_worker(task_agent_type)
        result = worker(state)
        # If the worker did not attach artifacts, create a stub artifact for traceability.
        if not result.get("artifacts") and task:
            try:
                ref = store_artifact(
                    {"summary": f"Executed task: {task.title}"},
                    kind="task_stub",
                    metadata={"task_id": task.id},
                    run_thread_id=thread_id or plan.plan_id,
                    task_id=task.id,
                )
                result.setdefault("artifacts", []).append(ref)
            except Exception:
                pass
        if sync_in_worker and task:
            try:
                upsert_task_from_spec(task, created_by_id=user_id)
            except Exception:
                # Avoid failing the worker path due to kanban sync issues.
                pass
        return result

    # Verification loop (L2) — optionally wrap the worker so critic-enabled
    # agents (triage/optimization) self-verify: grade the answer, and on failure
    # re-run once with the critique appended. Bounded by ``max_reflections``;
    # off by default (0) so the interactive path is unchanged. See critic.py +
    # docs/plans/LOOP_ENGINEERING_SELF_IMPROVEMENT_2026-07-19.md.
    if max_reflections > 0:
        from .critic import CRITIC_ENABLED_AGENTS, WorkerCritic, reflective_worker

        def _effective_agent_type(task) -> str:
            t = getattr(task, "agent_type", None)
            if force_worker_agent_type and (t or "").strip() != CLARIFY_AGENT_TYPE:
                t = force_worker_agent_type
            return (t or agent_type or "").strip()

        worker_fn = reflective_worker(
            worker_fn,
            WorkerCritic(),
            max_reflections=max_reflections,
            agent_type_of=_effective_agent_type,
            enabled_agents=CRITIC_ENABLED_AGENTS,
        )

    from components.agents.domain.value_objects.plan_schemas import ExecutionBudget

    execution_budget = ExecutionBudget(
        max_iterations=max_iterations,
        max_tasks=max(len(plan.tasks or []) * 3, 100),  # 3x the initial plan size, min 100
        time_budget_seconds=time_budget_seconds,
        max_worker_failures=max_worker_failures,
    )
    graph = build_orchestrator(
        planner_fn=planner_fn,
        worker_fn=worker_fn,
        synthesizer_fn=llm_synthesizer if use_llm_synthesizer else None,
        budget=execution_budget,
        approval_required=approval_required,
        max_replans=max_replans,
    )
    # Pass user/workspace into the config so the DB-backed checkpointer
    # can populate DeepRun rows with the correct owner when it writes a
    # checkpoint before the row has been created elsewhere.  NOT NULL
    # violation on `ai_deeprun.user_id` observed locally when these
    # fields were missing.
    config = {
        "configurable": {
            "thread_id": run_thread,
            "plan_id": plan.plan_id,
            "user_id": user_id,
            "workspace_id": workspace_id,
        }
    }
    try:
        state = graph.invoke(
            {
                "plan": plan,
                "pending_tasks": list(plan.tasks or []),
                "completed_task_ids": [],
                "run_id": run_thread,
                "run_context": run_context,
            },
            config=config,
        )
    except Exception as exc:
        DeepRun.objects.filter(thread_id=run_thread).update(
            state=to_serializable({"error": str(exc)}),
            status=DeepRun.STATUS_FAILED,
            last_error=str(exc),
        )
        log_deep_event(run_thread, "run_failed", status=DeepRun.STATUS_FAILED, payload={"error": str(exc)})
        raise

    # Persist cost tracking into DeepRun.state['usage']
    from components.agents.application.services.execution_cost_tracker import ExecutionCostTracker

    cost_tracker = ExecutionCostTracker()
    # Extract token counts from run_metadata if the worker tracked them
    run_metadata = state.get("run_metadata") or {}
    if run_metadata.get("total_input_tokens"):
        cost_tracker.record_llm_call(
            input_tokens=run_metadata.get("total_input_tokens", 0),
            output_tokens=run_metadata.get("total_output_tokens", 0),
        )

    final_state = to_serializable(state)
    if isinstance(final_state, dict):
        final_state["usage"] = cost_tracker.snapshot()

    DeepRun.objects.filter(thread_id=run_thread).update(
        state=final_state,
        status=DeepRun.STATUS_COMPLETED,
    )
    log_deep_event(run_thread, "run_completed", status=DeepRun.STATUS_COMPLETED)
    return state


def resume_plan(thread_id: str, *, graph, plan_state: PlanState | None = None) -> PlanState:
    """
    Resume a previously interrupted graph run by thread_id. In langgraph 0.0.69,
    explicit Command(resume=...) is not available; callers should reuse the same
    checkpointer thread_id when invoking the graph.
    """
    return graph.invoke(plan_state or {}, config={"configurable": {"thread_id": thread_id}})

"""
Schema primitives for deep agent planning/execution.

These models are intentionally minimal and JSON-friendly to keep prompts small.
"""

from __future__ import annotations

import operator
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


class Priority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TaskStatus(str, Enum):
    todo = "todo"
    done = "done"
    archived = "archived"


class AssigneeType(str, Enum):
    human = "human"
    agent = "agent"


class ArtifactRef(BaseModel):
    """Reference to an artifact stored outside of the prompt context."""

    uri: str
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ColumnSuggestion(BaseModel):
    """Optional kanban column hint."""

    id: str | None = None
    title: str | None = None
    status_hint: TaskStatus | None = None


class BudgetLine(BaseModel):
    """Structured budget line for project planning outputs."""

    label: str
    amount: float
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskSpec(BaseModel):
    """
    Structured task definition emitted by the planner and consumed by workers/syncers.
    """

    id: str | None = None
    title: str
    description: str | None = None  # Model does not persist this yet; retained for planner IO.
    priority: Priority = Priority.medium
    due_date: datetime | None = None
    project_id: str | None = None
    workspace_id: str | None = None
    team_id: str | None = None
    column: ColumnSuggestion | None = None
    status: TaskStatus = TaskStatus.todo
    assignee_id: str | None = None
    assignee_type: AssigneeType = AssigneeType.human
    parent_task_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    order: int | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Per-task specialist routing. The planner picks the right
    # bounded-context agent for each task — ``budget_agent`` for
    # budget questions, ``sponsorship_agent`` for sponsor questions,
    # etc. ``None`` means "use the chat's default agent_type"
    # (back-compat for callers that pre-date per-task routing).
    # See the planner's system prompt for the catalog.
    agent_type: str | None = None


class PlanSpec(BaseModel):
    """Planner output containing the goal and its decomposed tasks."""

    plan_id: str
    goal: str
    tasks: list[TaskSpec] = Field(default_factory=list)
    budget_lines: list[BudgetLine] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Sentinel agent_type for clarifying tasks.
#
# The planner emits a TaskSpec with ``agent_type=CLARIFY_AGENT_TYPE``
# when the user's goal is too vague to route confidently to any
# specialist (e.g. "tldr", "summary", "how are we doing?"). The
# orchestrator handles these directly — no LangChain AgentExecutor
# dispatch, no LLM call — by surfacing ``task.description`` (or
# ``task.title`` as a fallback) as the user-visible answer.
#
# Before this sentinel existed (planner.system v3), clarifying
# tasks were routed to ``workspace_agent``. That agent has no
# "ask the user" tool, so it thrashed through ~17 tool-calling
# rounds before the synthesizer's honesty guard fired. See
# ``docs/rca/2026-06-08-clarify-task-thrash.md``.
CLARIFY_AGENT_TYPE = "clarify"


class WorkerResult(BaseModel):
    """Structured output expected from a worker node."""

    task_id: str | None = None
    summary: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_inputs: dict[str, Any] = Field(default_factory=dict)
    # True when this result came from a clarify short-circuit (the
    # planner emitted a clarifying task and the orchestrator skipped
    # agent dispatch). The synthesizer uses this to surface the
    # ``summary`` directly as the user-facing answer instead of
    # paraphrasing it through an LLM.
    is_clarification: bool = False


class ExecutionBudget(BaseModel):
    """Caps that prevent runaway deep agent loops.

    Inspired by the reference architecture's BudgetTracker pattern — every
    agent run must have hard limits on iterations, tasks, wall-clock time,
    and cumulative failures.  Without these, a circular dependency or a
    planner that keeps generating tasks will loop forever.
    """

    max_iterations: int = Field(default=50, description="Max scheduler->worker cycles before forced stop.")
    max_tasks: int = Field(default=100, description="Max total tasks (ready + completed) before forced stop.")
    time_budget_seconds: float = Field(default=300.0, description="Wall-clock seconds before forced stop.")
    max_worker_failures: int = Field(default=10, description="Cumulative worker failures before forced stop.")


def merge_run_metadata(current: dict[str, Any] | None, update: dict[str, Any] | None) -> dict[str, Any]:
    """LangGraph reducer for ``PlanState.run_metadata`` — dict deep-merge.

    ``run_metadata`` is written by many nodes: the scheduler (iteration_count,
    plan_status), the workers (rubric_verdicts / critic_scores / worker_error_* /
    worker_failures / worker_retries, fanned out via ``Send`` so their input
    state carries NO run_metadata), the synthesizer (goal_met), approval, and
    replan bookkeeping. As a plain last-value channel this had two proven
    failure modes:

    1. Two concurrent worker ``Send``s both returning ``run_metadata`` raised
       ``InvalidUpdateError`` and killed the whole run.
    2. Sequential tasks clobbered each other's stamps — each worker seeds from
       its ``Send`` payload (which has no run_metadata), so task B's
       ``rubric_verdicts`` overwrote task A's and only the last task's verdict
       reached the persisted ``DeepRun.state``.

    Merge semantics: later keys win for scalars/lists; nested dicts merge
    recursively, so per-task maps like ``rubric_verdicts`` / ``critic_scores``
    union by task_id instead of replacing wholesale. Deletion-by-omission is
    intentionally NOT supported — every node in the orchestrator is additive
    (read-copy-add); none removes keys.
    """
    merged: dict[str, Any] = dict(current or {})
    for key, value in (update or {}).items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_run_metadata(existing, value)
        else:
            merged[key] = value
    return merged


class PlanState(TypedDict, total=False):
    """
    Shared graph state used by the orchestrator.

    The Annotated lists enable LangGraph to merge results across concurrent
    workers; ``run_metadata`` carries a dict-deep-merge reducer for the same
    reason (see ``merge_run_metadata``).
    """

    plan: PlanSpec
    ready_tasks: list[TaskSpec]
    pending_tasks: list[TaskSpec]
    in_flight_task_ids: list[str]
    completed_task_ids: Annotated[list[str], operator.add]
    completed_tasks: Annotated[list[WorkerResult], operator.add]
    artifacts: Annotated[list[ArtifactRef], operator.add]
    final_output: Any
    run_metadata: Annotated[dict[str, Any], merge_run_metadata]
    run_id: str | None
    run_context: dict[str, Any]
    # Execution budget tracking (set by the orchestrator, checked by scheduler)
    iteration_count: int
    # LEGACY failure channel. A last-value int written from a worker's Send
    # payload can never accumulate (each worker seeds from an empty input
    # state) and two concurrent failing workers collide with
    # InvalidUpdateError. Failure records now live in
    # ``run_metadata["worker_failures"]`` (reducer-united); the count is
    # derived there (see orchestrator._derived_worker_failure_count, which
    # only falls back to this channel when no records exist).
    worker_failure_count: int
    start_time: float
    budget: dict[str, Any] | None

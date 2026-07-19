"""
Schema primitives for deep agent planning/execution.

These models are intentionally minimal and JSON-friendly to keep prompts small.
"""
from __future__ import annotations

import operator
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Annotated

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
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ColumnSuggestion(BaseModel):
    """Optional kanban column hint."""

    id: Optional[str] = None
    title: Optional[str] = None
    status_hint: Optional[TaskStatus] = None


class BudgetLine(BaseModel):
    """Structured budget line for project planning outputs."""

    label: str
    amount: float
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskSpec(BaseModel):
    """
    Structured task definition emitted by the planner and consumed by workers/syncers.
    """

    id: Optional[str] = None
    title: str
    description: Optional[str] = None  # Model does not persist this yet; retained for planner IO.
    priority: Priority = Priority.medium
    due_date: Optional[datetime] = None
    project_id: Optional[str] = None
    workspace_id: Optional[str] = None
    team_id: Optional[str] = None
    column: Optional[ColumnSuggestion] = None
    status: TaskStatus = TaskStatus.todo
    assignee_id: Optional[str] = None
    assignee_type: AssigneeType = AssigneeType.human
    parent_task_id: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    order: Optional[int] = None
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Per-task specialist routing. The planner picks the right
    # bounded-context agent for each task — ``budget_agent`` for
    # budget questions, ``sponsorship_agent`` for sponsor questions,
    # etc. ``None`` means "use the chat's default agent_type"
    # (back-compat for callers that pre-date per-task routing).
    # See the planner's system prompt for the catalog.
    agent_type: Optional[str] = None


class PlanSpec(BaseModel):
    """Planner output containing the goal and its decomposed tasks."""

    plan_id: str
    goal: str
    tasks: List[TaskSpec] = Field(default_factory=list)
    budget_lines: List[BudgetLine] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


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

    task_id: Optional[str] = None
    summary: str
    artifact_refs: List[ArtifactRef] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_inputs: Dict[str, Any] = Field(default_factory=dict)
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


class PlanState(TypedDict, total=False):
    """
    Shared graph state used by the orchestrator.

    The Annotated lists enable LangGraph to merge results across concurrent workers.
    """

    plan: PlanSpec
    ready_tasks: List[TaskSpec]
    pending_tasks: List[TaskSpec]
    in_flight_task_ids: List[str]
    completed_task_ids: Annotated[List[str], operator.add]
    completed_tasks: Annotated[List[WorkerResult], operator.add]
    artifacts: Annotated[List[ArtifactRef], operator.add]
    final_output: Any
    run_metadata: Dict[str, Any]
    run_id: Optional[str]
    run_context: Dict[str, Any]
    # Execution budget tracking (set by the orchestrator, checked by scheduler)
    iteration_count: int
    worker_failure_count: int
    start_time: float
    budget: Optional[Dict[str, Any]]

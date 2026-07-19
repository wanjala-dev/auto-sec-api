"""Commands and result types for deep-run orchestration.

Framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.shared_kernel.application.commands import Command


@dataclass(frozen=True, kw_only=True)
class DeepRunPlanCommand(Command):
    """Execute a pre-built plan with the specified agent type."""

    raw_plan: dict
    agent_type: str
    user_id: str
    workspace_id: str
    team_id: str | None = None
    agent_config: dict = field(default_factory=dict)
    thread_id: str | None = None
    sync_to_kanban: bool = True


@dataclass(frozen=True, kw_only=True)
class DeepPlanAndRunCommand(Command):
    """Generate a plan from a goal via LLM, then execute it."""

    goal: str
    agent_type: str
    user_id: str
    workspace_id: str
    plan_id: str = ""
    team_id: str | None = None
    agent_config: dict = field(default_factory=dict)
    model_name: str | None = None
    sync_to_kanban: bool = True
    # Free-form context dict the planner can read — currently carries
    # ``conversation_history`` (prior chat turns so the planner can
    # resolve cross-turn references) and may carry sector / pack
    # metadata. Type was historically ``str | None`` but every caller
    # actually passes a dict; the annotation now matches the real
    # contract. See planner system prompt for what keys it consumes.
    extra_context: dict | None = None
    deep_pack: str | None = None


@dataclass(frozen=True)
class DeepRunSuccess:
    plan_id: str
    state: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeepRunFailure:
    error: str
    status_code: int = 400

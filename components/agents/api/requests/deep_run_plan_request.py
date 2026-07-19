"""Request DTO for POST /ai/agents/deep/run-plan/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeepRunPlanRequest:
    """Input DTO for POST /ai/agents/deep/run-plan/ endpoint.

    Executes a provided PlanSpec with an existing agent type.
    """
    plan: dict[str, Any] = field(default_factory=dict)
    agent_type: str = "task_agent"
    workspace_id: str | None = None
    team_id: str | None = None
    thread_id: str | None = None
    agent_config: dict[str, Any] = field(default_factory=dict)
    plan_id: str | None = None
    sync_to_kanban: bool = True

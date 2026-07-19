"""Request DTO for POST /ai/agents/deep/plan-and-run/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeepPlanAndRunRequest:
    """Input DTO for POST /ai/agents/deep/plan-and-run/ endpoint.

    One-shot plan and execute - plans and runs in a single call.
    """
    goal: str
    workspace_id: str
    agent_type: str = "task_agent"
    team_id: str | None = None
    plan_id: str = ""
    agent_config: dict[str, Any] = field(default_factory=dict)
    model_name: str | None = None
    sync_to_kanban: bool = True
    context: dict[str, Any] | None = None
    deep_pack: dict[str, Any] | None = None

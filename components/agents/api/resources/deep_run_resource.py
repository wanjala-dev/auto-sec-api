"""Response DTO for deep run endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlanStepResource:
    """A single step in a plan."""
    step_id: str
    action: str
    description: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class DeepRunResource:
    """Output DTO for deep run endpoints."""
    plan_id: str
    state: dict[str, Any] = field(default_factory=dict)
    steps: list[PlanStepResource] = field(default_factory=list)
    status: str = "pending"
    progress: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

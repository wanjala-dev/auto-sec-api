"""Commands and result types for agent lifecycle operations.

Framework-free.  Commands extend the shared-kernel ``Command`` base
so they can be dispatched through the Command Bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from components.shared_kernel.application.commands import Command


# ── Create agent ──────────────────────────────────────────────────────

@dataclass(frozen=True, kw_only=True)
class CreateAgentCommand(Command):
    agent_type: str
    user_id: str
    workspace_id: str
    config: dict = field(default_factory=dict)
    department_id: str | None = None


@dataclass(frozen=True)
class CreateAgentSuccess:
    agent_info: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CreateAgentFailure:
    error: str
    status_code: int = 400


# ── Pause / Resume agent ─────────────────────────────────────────────

@dataclass(frozen=True, kw_only=True)
class AgentStateCommand(Command):
    """Pause or resume an agent."""

    agent_id: str
    user_id: str
    action: str  # "pause" | "resume"


@dataclass(frozen=True)
class AgentStateSuccess:
    message: str
    state: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentStateFailure:
    error: str
    status_code: int = 400


# ── Delete agent ─────────────────────────────────────────────────────

@dataclass(frozen=True, kw_only=True)
class DeleteAgentCommand(Command):
    agent_id: str
    user_id: str


@dataclass(frozen=True)
class DeleteAgentSuccess:
    message: str = "Agent deleted successfully"


@dataclass(frozen=True)
class DeleteAgentFailure:
    error: str
    status_code: int = 400

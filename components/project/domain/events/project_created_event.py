"""Domain event: a Project was successfully created.

Published from ``CreateProjectUseCase`` after the underlying port
returns ``CreateProjectResult(success=True, ...)``. Carries the
identifiers downstream consumers need (workspace, team, project,
creator) without forcing a DB round-trip.

Designed for the Phase 3 Agents-as-Teammates flow (Action List items
#14 + #24): the ``project_specialist_handler`` subscribes via
``@subscribes_to(ProjectCreated)`` and posts a setup-nudge task to
the agent team Kanban so a new project doesn't sit configured-but-empty.

Adding a new subscriber later is a one-file change — the registry
auto-discovers handlers in ``components/agents/application/handlers/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ProjectCreated(DomainEvent):
    project_id: UUID
    workspace_id: UUID | None
    team_id: UUID | None
    created_by_id: UUID | None
    title: str
    created_at: datetime

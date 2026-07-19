"""Port: Task creation operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CreateTaskCommand:
    title: str
    column_id: str
    user_id: str
    project_id: str | None = None
    event_id: str | None = None
    campaign_id: str | None = None
    recipient_id: str | None = None
    grant_id: str | None = None
    workspace_id: str | None = None
    # Provenance label for upstream-system-driven tasks (e.g.
    # ``ai.book_balance.budget_overrun``). Empty/None for
    # human-created tasks. Phase 4 of the Agents-as-Teammates
    # migration uses this to route the workflow trigger.
    source_type: str | None = None
    # Free-form narrative. For specialist-agent tasks this is the
    # detector's human-readable summary (previously stored on
    # ``AIAction.summary``).
    description: str = ""
    # Structured payload — agent attribution + detector context for
    # AI-finding tasks (previously split across ``AIAction.payload``,
    # ``AIAction.context``, ``AIAction.agent_type``, etc.).
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional user ids to assign to the created task (M2M ``assigned_to``).
    # Default None → no assignment (backwards-compatible for every existing
    # caller). Used by the sign-off materializer to assign a pending
    # sign-off task to the workspace owner. When set, the adapter adds the
    # users AND fires the ``task_assigned`` workflow event per assignee,
    # mirroring the normal ``AssignUsersToTaskView`` assignment path.
    assigned_to_ids: list[str] | None = None
    # Optional planning fields captured at creation (the task-creation
    # wizard). Previously settable only post-creation via PATCH — which is
    # why the create modal could offer nothing beyond a title. ``due_date``
    # is an ISO date or datetime string; ``priority`` is a
    # ``Task.Priority`` value (low/medium/high/urgent, case-insensitive).
    # None → model defaults.
    due_date: str | None = None
    priority: str | None = None


@dataclass
class CreateTaskResult:
    task_id: str = ""
    team_id: str = ""
    workspace_id: str = ""
    created_by: str = ""
    updated_at: str = ""
    title: str = ""
    created_at: str = ""
    project_id: str | None = None
    event_id: str | None = None
    campaign_id: str | None = None
    recipient_id: str | None = None
    grant_id: str | None = None
    status: str = ""
    column_id: str = ""
    order: int = 0
    description: str = ""
    due_date: str | None = None
    priority: str = ""
    assigned_to_ids: list[str] = field(default_factory=list)


class CreateTaskPort(abc.ABC):
    """Secondary port for task creation."""

    @abc.abstractmethod
    def create_task(self, *, command: CreateTaskCommand) -> CreateTaskResult:
        """Create a task in the given column.

        Validates column, team active status, membership, project
        cross-references, plan limits, creates the task, emits workflow
        event, and auto-follows workspace.

        Raises ColumnNotFoundError if column does not exist.
        Raises TaskValidationError for business rule violations.
        Raises TeamMembershipRequiredError if user lacks team access.
        Raises TaskLimitExceededError if plan limit reached.
        """
        ...

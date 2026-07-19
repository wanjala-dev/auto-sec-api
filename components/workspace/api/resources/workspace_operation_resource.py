"""Resource DTO for workspace operation entities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceOperationResource:
    """Output DTO for workspace operation detail endpoints.

    Represents a single workspace operation (checklist item).
    """
    id: int | None = None
    workspace: str | None = None
    name: str | None = None
    checked: bool = False
    text: str | None = None


@dataclass(frozen=True)
class WorkspaceOperationCollectionResource:
    """Output DTO for workspace operation list endpoints.

    Represents a collection of workspace operations.
    """
    items: list[WorkspaceOperationResource] | None = None
    count: int = 0

"""Request DTO for batch workspace operation update endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchUpdateWorkspaceOperationsRequest:
    """Input DTO for PUT /workspaces/operations/ endpoint.

    Handles batch updates of workspace operations (e.g., multiple checked statuses).
    """
    operations: list[dict]

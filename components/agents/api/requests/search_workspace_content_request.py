"""Request DTO for POST /ai/search/workspaces/ endpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchWorkspaceContentRequest:
    """Input DTO for POST /ai/search/workspaces/ endpoint.

    Searches workspace content using vector similarity.
    """
    query: str
    workspace_id: str
    k: int = 10
    filters: dict[str, Any] = field(default_factory=dict)

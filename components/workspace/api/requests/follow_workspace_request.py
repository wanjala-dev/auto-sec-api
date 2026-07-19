"""Request DTO for workspace follow endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FollowWorkspaceRequest:
    """Input DTO for POST/DELETE /workspaces/follow/ endpoint.

    Handles workspace follow/unfollow operations with batch support.
    """
    workspace_ids: list[str] | None = None

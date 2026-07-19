from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceResource:
    """Output DTO for workspace details.

    Represents a workspace object returned by workspace-related endpoints.
    """
    id: str
    workspace_name: str
    workspace_owner: dict | None = None
    photo_url: str | None = None
    plan: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class WorkspaceListResource:
    """Output DTO for GET /workspaces/<pk>/ endpoint response.

    Returns a list of workspaces for a user.
    """
    data: list[WorkspaceResource]


@dataclass(frozen=True)
class TeamResource:
    """Output DTO for team details.

    Represents a team/group within a workspace.
    """
    id: str
    status: str
    workspace: dict | None = None
    plan: dict | None = None
    members: list[dict] | None = None


@dataclass(frozen=True)
class UserWithWorkspacesResource:
    """Output DTO for GET /detail/<id>/ endpoint response.

    Returns comprehensive user data including teams and workspaces.
    """
    data: dict | None = None

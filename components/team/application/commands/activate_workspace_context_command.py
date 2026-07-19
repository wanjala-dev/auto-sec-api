"""Command DTO for activating a workspace's team context in one call.

Front end used to make two sequential HTTP calls when switching
workspaces: ``GET /seeds/<workspace_id>/teams/`` then
``POST /team/activate/`` with the first team's id. The two-roundtrip
latency was visible in the UI (~1–2s). This command lets the frontend
hand the backend a workspace id and have the activation pick a team
server-side in a single round-trip.

Picking the "first" team mirrors the frontend's ``pickFirstTeamId``
behaviour (first accessible team in the workspace). When the backend
later models a per-user "preferred team per workspace" preference, the
selection can swap to that without changing the endpoint contract.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivateWorkspaceContextCommand:
    """Command to activate a workspace's team context.

    Attributes:
        workspace_id: The ID (UUID) of the workspace to switch to. The
            backend picks a team in this workspace that the actor has
            access to and activates it.
        actor_id: The ID of the authenticated user.
        is_staff: Whether the actor is a staff member.
        is_superuser: Whether the actor is a superuser.
    """

    workspace_id: object
    actor_id: object
    is_staff: bool = False
    is_superuser: bool = False

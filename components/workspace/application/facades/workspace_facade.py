"""Application-layer facade exposing workspace utilities to other contexts.

This facade re-exports workspace infrastructure utilities that have cross-context
dependencies, allowing other contexts to use them without directly importing from
the infrastructure layer.
"""

from components.workspace.infrastructure.adapters.workspace_utils import (
    ensure_team_board_columns,
    ensure_team_membership,
    ensure_workspace_follower,
    ensure_workspace_membership,
    ensure_workspace_scaffolding,
    user_is_workspace_admin_or_owner,
    user_is_workspace_member,
)

__all__ = [
    "ensure_team_board_columns",
    "ensure_team_membership",
    "ensure_workspace_follower",
    "ensure_workspace_membership",
    "ensure_workspace_scaffolding",
    "user_is_workspace_admin_or_owner",
    "user_is_workspace_member",
]

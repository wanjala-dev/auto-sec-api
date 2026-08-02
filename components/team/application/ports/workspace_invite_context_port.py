"""Port (team-owned): workspace-side reads the persona-invite CREATE flow needs.

Creating an invitation must validate the target workspace, authorize the
inviter (owner/admin RBAC), validate any permission-group ids belong to the
workspace, and resolve a team for team-attached personas. All of that reads
``workspace``-owned models (``Workspace`` / ``WorkspaceMembership`` /
``WorkspaceGroup`` / ``Team``). The team application layer must not read those
models directly (architecture-skill C3), so it depends on this read seam; the
adapter delegates to ``workspace``'s application surface.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceInviteContext:
    """Raw facts resolved from the workspace context.

    The use case (not this DTO / the adapter) maps these to error + status code,
    so the *ordering* of the workspace-404 / auth-403 / team-required-400 /
    team-not-found-404 checks lives in one place and matches ``main`` exactly.

    ``team_found`` defaults True and stays True whenever a team lookup was not
    attempted (no team required, or team required but ``team_id`` omitted — that
    latter case is the use case's 400, not this DTO's 404).
    """

    workspace_found: bool = False
    authorized: bool = False
    team_found: bool = True
    validated_group_ids: list[str] | None = None


class WorkspaceInviteContextPort(abc.ABC):
    @abc.abstractmethod
    def get_inviter_email(self, *, inviter_user_id: str) -> str | None:
        """Return the inviter's (lower-cased) email for the self-invite guard,
        or None when the user can't be found."""
        ...

    @abc.abstractmethod
    def resolve_invite_context(
        self,
        *,
        workspace_id: str,
        inviter_user_id: str | None,
        inviter_is_staff: bool,
        inviter_is_superuser: bool,
        persona: str,
        team_required: bool,
        team_id: str | None,
        permission_group_ids: list[str] | None,
    ) -> WorkspaceInviteContext:
        """Validate the workspace, authorize the inviter (owner/admin), validate
        the permission-group ids, and — only when a team is required AND a
        ``team_id`` is supplied — resolve the team (``team_found``). It does NOT
        emit errors or decide ordering; the use case does."""
        ...

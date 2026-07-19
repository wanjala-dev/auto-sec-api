from __future__ import annotations

import uuid

from django.core.exceptions import ObjectDoesNotExist

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import WorkspaceMembership
from components.team.domain.errors import TeamMembershipRequiredError


def _actor_is_workspace_admin_or_owner(workspace, actor_id) -> bool:
    """True when the actor is the workspace owner or has admin/owner role.

    Admin-level access lets the user interact with every team in the
    workspace, including the seeded Agents team (AI-only members). Branches
    on ``WorkspaceMembership.role`` per ADR 0002.
    """
    if not workspace or actor_id is None:
        return False
    if str(workspace.workspace_owner_id) == str(actor_id):
        return True
    return WorkspaceMembership.objects.filter(
        workspace_id=workspace.id,
        user_id=actor_id,
        status=WorkspaceMembership.Status.ACTIVE,
        role__in=(
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
        ),
    ).exists()


class OrmTeamContextRepository:
    def get_accessible_team(
        self,
        *,
        team_id: int,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        try:
            team = Team.objects.select_related("workspace").get(pk=team_id, status=Team.ACTIVE)
        except Team.DoesNotExist as exc:
            raise ObjectDoesNotExist("Team not found.") from exc

        if is_staff or is_superuser:
            return team
        if _actor_is_workspace_admin_or_owner(team.workspace, actor_id):
            return team
        if team.members.filter(id=actor_id).exists():
            return team

        raise TeamMembershipRequiredError("You must be a member of this team.")

    def resolve_active_team(
        self,
        *,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        """Resolve the user's active team from their profile and validate access."""
        profile, _ = UserProfile.objects.get_or_create(user_id=actor_id)
        active_team_id = profile.active_team_id
        if not active_team_id:
            raise ObjectDoesNotExist("User has no active team.")
        return self.get_accessible_team(
            team_id=active_team_id,
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def activate_team_for_user(self, *, actor_id, team) -> None:
        profile, _ = UserProfile.objects.get_or_create(user_id=actor_id)
        updates = []

        if profile.active_team_id != team.id:
            profile.active_team_id = team.id
            updates.append("active_team_id")
        if profile.active_workspace_id != team.workspace_id:
            profile.active_workspace_id = team.workspace_id
            updates.append("active_workspace_id")

        if updates:
            profile.save(update_fields=updates)

    def activate_workspace_for_user(self, *, actor_id, workspace_id) -> None:
        """Persist the active workspace WITHOUT a team.

        For a workspace member who belongs to no internal team — e.g. a
        sponsor / viewer (ADR 0002). Sets ``active_workspace_id`` and
        clears ``active_team_id`` to the ``0`` "no team" sentinel (the
        field is a non-null IntegerField) so request-routing that reads the
        active team (projects/tasks/timers) never points at the *previous*
        workspace's team after the switch. The caller is responsible for
        verifying the actor may access this workspace.
        """
        workspace_uuid = (
            workspace_id
            if isinstance(workspace_id, uuid.UUID)
            else uuid.UUID(str(workspace_id))
        )
        profile, _ = UserProfile.objects.get_or_create(user_id=actor_id)
        updates = []

        if profile.active_workspace_id != workspace_uuid:
            profile.active_workspace_id = workspace_uuid
            updates.append("active_workspace_id")
        if profile.active_team_id:
            profile.active_team_id = 0
            updates.append("active_team_id")

        if updates:
            profile.save(update_fields=updates)

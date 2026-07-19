from __future__ import annotations

import logging

from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Workspace
from components.workspace.application.facades.workspace_facade import (
    ensure_team_membership,
    ensure_workspace_follower,
    ensure_workspace_membership,
    ensure_workspace_scaffolding,
)
from components.workspace.domain.policies.contributor_enrollment_policy_service import (
    ContributorEnrollmentPolicyService,
)
from components.team.domain.policies.team_membership_policy_service import (
    TeamMembershipPolicyService,
)
from components.team.application.ports.team_membership_port import TeamMembershipPort

logger = logging.getLogger(__name__)

class OrmTeamMembershipRepository(TeamMembershipPort):
    def __init__(
        self,
        *,
        team_membership_policy: TeamMembershipPolicyService,
        contributor_enrollment_policy: ContributorEnrollmentPolicyService,
    ) -> None:
        self.team_membership_policy = team_membership_policy
        self.contributor_enrollment_policy = contributor_enrollment_policy

    def get_or_create_default_team(self, workspace):
        if not workspace:
            return None

        team_title = self._default_team_title(workspace)
        team = (
            Team.objects.filter(workspace=workspace, title__iexact=team_title)
            .order_by("created_at")
            .select_related("workspace", "created_by")
            .first()
        )
        if team:
            self._ensure_default_team_is_active(team=team, workspace=workspace)
            return team

        owner = getattr(workspace, "workspace_owner", None)
        if not owner:
            return None

        try:
            default_team, _ = ensure_workspace_scaffolding(
                workspace,
                owner,
                team_title=team_title,
            )
            return default_team
        except Exception:  # noqa: BLE001
            logger.exception(
                "Unable to ensure default team for workspace %s",
                getattr(workspace, "id", "unknown"),
            )
            return None

    def enroll_user_in_team(
        self,
        user,
        workspace,
        team,
        *,
        mark_contributor: bool = True,
        update_active_context: bool = False,
    ) -> None:
        if not user or not team:
            return

        if self.contributor_enrollment_policy.should_mark_contributor(
            mark_contributor=mark_contributor,
            is_contributor=getattr(user, "is_contributor", False),
        ):
            user.is_contributor = True
            user.save(update_fields=["is_contributor"])

        team.members.add(user)
        ensure_workspace_follower(workspace, user)
        ensure_workspace_membership(workspace, user)
        ensure_team_membership(team, user)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        updates = self.team_membership_policy.profile_context_updates(
            current_active_workspace_id=profile.active_workspace_id,
            current_active_team_id=profile.active_team_id,
            workspace_id=getattr(workspace, "id", None),
            team_id=getattr(team, "id", None),
            update_active_context=update_active_context,
        )
        if updates:
            for field, value in updates.items():
                setattr(profile, field, value)
            profile.save(update_fields=list(updates))

    def ensure_contributor_membership(self, user, workspace):
        team = self.get_or_create_default_team(workspace)
        if not team or not user:
            return team

        self.enroll_user_in_team(
            user,
            workspace,
            team,
            update_active_context=False,
        )
        return team

    @staticmethod
    def _is_personal_workspace(workspace: Workspace) -> bool:
        if not workspace:
            return False
        if getattr(workspace, "sector_id", None) == "personal":
            return True
        return workspace.sectors.filter(slug="personal").exists()

    def _default_team_title(self, workspace: Workspace) -> str:
        return self.team_membership_policy.default_team_title(
            is_personal_workspace=self._is_personal_workspace(workspace),
        )

    def _ensure_default_team_is_active(self, *, team, workspace) -> None:
        updates = []
        if self.team_membership_policy.should_activate_team(
            current_status=team.status,
            active_status=Team.ACTIVE,
        ):
            team.status = Team.ACTIVE
            updates.append("status")
        if updates:
            team.save(update_fields=updates)

        owner = getattr(workspace, "workspace_owner", None)
        if owner and not team.members.filter(id=owner.id).exists():
            team.members.add(owner)

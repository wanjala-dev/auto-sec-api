"""ORM adapter for the MembershipPort.

Translates unified access-control queries into Django ORM lookups
against WorkspaceMembership, TeamMembership, and UserProfile.
"""

from __future__ import annotations

from components.membership.application.ports.membership_port import (
    AccessCheckResult,
    ActiveContext,
    MembershipPort,
)


class OrmMembershipRepository(MembershipPort):
    """Django ORM implementation of MembershipPort."""

    # ── workspace access ────────────────────────────────────────────

    def check_workspace_access(
        self,
        *,
        user_id: int,
        workspace_id: str,
        required_role: str | None = None,
    ) -> AccessCheckResult:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        qs = WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user_id,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        membership = qs.first()
        if membership is None:
            return AccessCheckResult(allowed=False, reason="Not a workspace member.")

        if required_role is not None:
            role_hierarchy = {
                "owner": 4,
                "admin": 3,
                "member": 2,
                "viewer": 1,
            }
            user_level = role_hierarchy.get(membership.role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            if user_level < required_level:
                return AccessCheckResult(
                    allowed=False,
                    role=membership.role,
                    reason=f"Requires '{required_role}' role, user has '{membership.role}'.",
                )

        return AccessCheckResult(allowed=True, role=membership.role)

    # ── team access ─────────────────────────────────────────────────

    def check_team_access(
        self,
        *,
        user_id: int,
        team_id: int,
        required_role: str | None = None,
    ) -> AccessCheckResult:
        from infrastructure.persistence.team.models import TeamMembership

        qs = TeamMembership.objects.filter(
            team_id=team_id,
            user_id=user_id,
            status=TeamMembership.Status.ACTIVE,
        )
        membership = qs.first()
        if membership is None:
            return AccessCheckResult(allowed=False, reason="Not a team member.")

        if required_role is not None:
            role_hierarchy = {
                "lead": 3,
                "editor": 2,
                "viewer": 1,
            }
            user_level = role_hierarchy.get(membership.role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            if user_level < required_level:
                return AccessCheckResult(
                    allowed=False,
                    role=membership.role,
                    reason=f"Requires '{required_role}' role, user has '{membership.role}'.",
                )

        return AccessCheckResult(allowed=True, role=membership.role)

    # ── active context ──────────────────────────────────────────────

    def resolve_active_context(self, *, user_id: int) -> ActiveContext:
        from infrastructure.persistence.users.models import UserProfile

        try:
            profile = UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            return ActiveContext(user_id=user_id)

        return ActiveContext(
            user_id=user_id,
            active_workspace_id=(
                str(profile.active_workspace_id) if profile.active_workspace_id else None
            ),
            active_team_id=profile.active_team_id,
        )

    # ── role queries ────────────────────────────────────────────────

    def list_workspace_roles(
        self,
        *,
        user_id: int,
        workspace_id: str,
    ) -> list[str]:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        return list(
            WorkspaceMembership.objects.filter(
                workspace_id=workspace_id,
                user_id=user_id,
                status=WorkspaceMembership.Status.ACTIVE,
            ).values_list("role", flat=True)
        )

    def list_team_roles(
        self,
        *,
        user_id: int,
        team_id: int,
    ) -> list[str]:
        from infrastructure.persistence.team.models import TeamMembership

        return list(
            TeamMembership.objects.filter(
                team_id=team_id,
                user_id=user_id,
                status=TeamMembership.Status.ACTIVE,
            ).values_list("role", flat=True)
        )

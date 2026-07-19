"""ORM-backed adapter for user workspace/team context queries.

Extracted from identity/api/users_controller.py to decouple the identity
controller from direct Workspace/WorkspaceMembership/Team ORM access.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from components.identity.application.ports.user_context_query_port import UserContextQueryPort
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


class OrmUserContextQueryRepository(UserContextQueryPort):
    """Django ORM implementation of user context reads."""

    def get_accessible_workspace_ids(self, *, user_id: Any) -> list[str]:
        # Use the default manager (status="active"), NOT all_objects(): archived
        # (status="inactive") workspaces must not leak into me/summary's
        # workspace_context. The member `workspaces` list uses the default
        # manager too, so all_objects() here made the two disagree — an owner's
        # archived org appeared in org_workspace_ids but not the member list, and
        # the frontend then 404'd fetching it. These two methods feed only the
        # user-context/me-summary read; no authorization path depends on them.
        ids = (
            Workspace.objects.filter(
                Q(workspace_owner_id=user_id)
                | Q(memberships__user_id=user_id, memberships__status=WorkspaceMembership.Status.ACTIVE)
                | Q(workspace_teams__members__id=user_id)
            )
            .values_list("id", flat=True)
            .distinct()
        )
        return [str(ws_id) for ws_id in ids]

    def get_org_membership_count(self, *, user_id: Any) -> int:
        # Active-only (default manager) for the same reason as
        # get_accessible_workspace_ids — don't count archived workspaces.
        return (
            Workspace.objects.filter(
                Q(workspace_owner_id=user_id)
                | Q(memberships__user_id=user_id, memberships__status=WorkspaceMembership.Status.ACTIVE)
                | Q(workspace_teams__members__id=user_id)
            )
            .distinct()
            .count()
        )

    def is_staff_or_superuser(self, *, user_id: Any) -> bool:
        try:
            user = CustomUser.objects.only("is_staff", "is_superuser").get(id=user_id)
        except CustomUser.DoesNotExist:
            return False
        return bool(user.is_staff or user.is_superuser)

    def get_active_workspace_id(self, *, user_id: Any) -> str | None:
        accessible = self.get_accessible_workspace_ids(user_id=user_id)
        try:
            profile = UserProfile.objects.only("active_workspace_id").get(user_id=user_id)
            ws_id = getattr(profile, "active_workspace_id", None)
        except UserProfile.DoesNotExist:
            ws_id = None
        ws_id = str(ws_id) if ws_id else None
        # The stored preference wins ONLY if it still points at a workspace the
        # user can access. Otherwise (unset, or pointing at an archived/left
        # workspace) fall back to their first accessible active workspace, so the
        # HUD always resolves a workspace for anyone who has one — not just users
        # seeded through create_persona_user. Read-only: no write side effects.
        if ws_id and ws_id in accessible:
            return ws_id
        return accessible[0] if accessible else None

    def infer_workspace_kind(self, *, workspace_id: Any) -> str | None:
        if not workspace_id:
            return None
        try:
            workspace = Workspace.objects.all_objects().only("workspace_type").get(id=workspace_id)
        except Workspace.DoesNotExist:
            return None

        if getattr(workspace, "workspace_type", None) == Workspace.PERSONAL:
            return "personal"
        return "organization"

    def infer_workspace_role(self, *, user_id: Any, workspace_id: Any) -> str | None:
        if not user_id or not workspace_id:
            return None

        try:
            workspace = Workspace.objects.all_objects().only("workspace_owner_id").get(id=workspace_id)
        except Workspace.DoesNotExist:
            return None

        if workspace.workspace_owner_id == user_id:
            return WorkspaceMembership.Role.OWNER

        membership_role = (
            WorkspaceMembership.objects.filter(
                workspace_id=workspace_id,
                user_id=user_id,
                status=WorkspaceMembership.Status.ACTIVE,
            )
            .values_list("role", flat=True)
            .first()
        )
        if membership_role:
            return membership_role

        if Team.objects.filter(workspace_id=workspace_id, members__id=user_id).exists():
            return WorkspaceMembership.Role.MEMBER
        if Workspace.objects.all_objects().filter(id=workspace_id, followers__id=user_id).exists():
            return "follower"
        return None

    def is_workspace_owner(self, *, user_id: Any, workspace_id: Any) -> bool:
        if not user_id or not workspace_id:
            return False
        return (
            Workspace.objects.all_objects()
            .filter(
                id=workspace_id,
                workspace_owner_id=user_id,
            )
            .exists()
        )

    def get_active_team_ids(self, *, user_id: Any) -> list[str]:
        ids = Team.objects.filter(members__id=user_id, status="active").values_list("id", flat=True).order_by("-id")
        return [str(tid) for tid in ids]

    def get_workspace_default_currency(self, *, workspace_id: Any) -> str | None:
        if not workspace_id:
            return None
        currency = Workspace.objects.filter(id=workspace_id).values_list("default_currency", flat=True).first()
        if not currency:
            return None
        return str(currency).strip().upper() or None

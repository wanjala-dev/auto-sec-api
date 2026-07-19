from __future__ import annotations

import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from components.team.domain.errors import (
    TeamConflictError,
    TeamMembershipRequiredError,
    TeamValidationError,
    WorkspaceMembershipRequiredError,
)
from components.workspace.application.facades.workspace_facade import (
    ensure_team_board_columns,
    ensure_team_membership,
    ensure_workspace_membership,
    user_is_workspace_member,
)
from infrastructure.persistence.project.models import Column
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Workspace


class OrmTeamManagementRepository:
    MUTABLE_TEAM_FIELDS = {
        "title",
        "kind",
        "privacy",
        "status",
    }

    @transaction.atomic
    def create_team(
        self,
        *,
        title: str,
        workspace_id,
        actor,
    ):
        try:
            workspace = Workspace.objects.get(id=uuid.UUID(str(workspace_id)))
        except (Workspace.DoesNotExist, ValueError, TypeError, AttributeError) as exc:
            raise TeamValidationError("Invalid user or workspace ID.") from exc

        if not user_is_workspace_member(actor, workspace):
            raise WorkspaceMembershipRequiredError("You must belong to the organization to perform this action.")

        if Team.objects.filter(title=title, created_by=actor).exists():
            raise TeamConflictError("A team with the same name already exists!")

        team = Team.objects.create(
            title=title,
            created_by=actor,
            workspace=workspace,
        )
        team.members.add(actor)

        ensure_workspace_membership(workspace, actor)
        ensure_team_membership(team, actor)
        self._activate_default_context(actor=actor, team=team, workspace=workspace)
        ensure_team_board_columns(workspace, team, actor)
        self._ensure_done_column(team=team, workspace=workspace, actor=actor)

        return team

    def update_active_team(
        self,
        *,
        actor,
        validated_data: dict,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        team = self._get_active_team_for_actor(
            actor=actor,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

        updates = []
        for field_name, value in validated_data.items():
            if field_name not in self.MUTABLE_TEAM_FIELDS:
                continue
            if getattr(team, field_name) == value:
                continue
            setattr(team, field_name, value)
            updates.append(field_name)

        if updates:
            team.save(update_fields=updates)

        return team

    @staticmethod
    def _activate_default_context(*, actor, team, workspace) -> None:
        userprofile, _ = UserProfile.objects.get_or_create(user=actor)
        updates = []
        if not userprofile.active_team_id:
            userprofile.active_team_id = team.id
            updates.append("active_team_id")
        if not userprofile.active_workspace_id:
            userprofile.active_workspace_id = workspace.id
            updates.append("active_workspace_id")
        if updates:
            userprofile.save(update_fields=updates)

    @staticmethod
    def _ensure_done_column(*, team, workspace, actor) -> None:
        done_column, _ = Column.objects.get_or_create(
            project=None,
            team=team,
            workspace=workspace,
            title="Done",
            defaults={
                "order": 7,
                "created_by": actor,
            },
        )
        updates = []
        if done_column.order != 7:
            done_column.order = 7
            updates.append("order")
        if done_column.created_by_id is None:
            done_column.created_by = actor
            updates.append("created_by")
        if updates:
            done_column.save(update_fields=updates)

    @staticmethod
    def _get_active_team_for_actor(*, actor, is_staff: bool = False, is_superuser: bool = False):
        try:
            profile = UserProfile.objects.get(user=actor)
        except UserProfile.DoesNotExist as exc:
            raise ObjectDoesNotExist("User profile not found.") from exc

        if not profile.active_team_id:
            raise ObjectDoesNotExist("Active team not found.")

        try:
            team = Team.objects.get(pk=profile.active_team_id, status=Team.ACTIVE)
        except Team.DoesNotExist as exc:
            raise ObjectDoesNotExist("Active team not found.") from exc

        if not OrmTeamManagementRepository._can_manage_team(
            actor=actor,
            team=team,
            is_staff=is_staff,
            is_superuser=is_superuser,
        ):
            raise TeamMembershipRequiredError("You must be a member of this team.")

        return team

    @staticmethod
    def _can_manage_team(*, actor, team, is_staff: bool = False, is_superuser: bool = False) -> bool:
        if is_staff or is_superuser:
            return True
        actor_id = getattr(actor, "id", None)
        if str(team.workspace.workspace_owner_id) == str(actor_id):
            return True
        # Workspace admins get implicit access to every team in their
        # workspace (ADR 0002 — RBAC reads WorkspaceMembership.role, never
        # persona).
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        if WorkspaceMembership.objects.filter(
            workspace_id=team.workspace_id,
            user_id=actor_id,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=(
                WorkspaceMembership.Role.OWNER,
                WorkspaceMembership.Role.ADMIN,
            ),
        ).exists():
            return True
        return team.members.filter(id=actor_id).exists()

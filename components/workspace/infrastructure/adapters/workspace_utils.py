"""Shared utilities for workspace setup and scaffolding."""

from __future__ import annotations

from django.utils import timezone

from infrastructure.persistence.project.models import Column
from infrastructure.persistence.team.models import Team, TeamMembership
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


def ensure_workspace_scaffolding(workspace, owner, *, team_title: str = "General") -> tuple[Team, None]:
    """Ensure a workspace has the baseline structures required by the app.

    Creates/updates the workspace's default team, assigns the owner, and wires
    up owner membership + the default kanban board columns.

    Returns ``(team, None)`` — the second slot historically carried a default
    Budget, which is no longer provisioned here. Callers that unpack
    ``team, _ = ...`` remain compatible.
    """

    team_defaults = {
        "created_by": owner,
        "status": Team.ACTIVE,
        "privacy": Team.PRIVATE,
        "is_default": True,
    }
    # One default ("home") team per workspace. Prefer an EXISTING default team
    # regardless of its title so neither bootstrap nor downstream seeding ever
    # creates a second home team (this is the root fix for the historical
    # "Contributors" + "Default Team" duplicate). Fall back to a title match
    # (legacy default teams created before is_default existed), else create one.
    team = (
        Team.objects.filter(workspace=workspace, is_default=True).first()
        or Team.objects.filter(workspace=workspace, title=team_title).first()
    )
    if team is None:
        team = Team.objects.create(workspace=workspace, title=team_title, **team_defaults)
    elif not team.is_default:
        team.is_default = True
        team.save(update_fields=["is_default"])

    if team.status != Team.ACTIVE:
        Team.objects.filter(id=team.id).update(status=Team.ACTIVE)
        team.refresh_from_db()

    team.members.add(owner)
    ensure_workspace_membership(workspace, owner, role=WorkspaceMembership.Role.OWNER)
    ensure_team_membership(team, owner, role=TeamMembership.Role.LEAD)

    ensure_team_board_columns(workspace, team, owner)

    return team, None


def ensure_workspace_follower(workspace, user: CustomUser) -> None:
    """Ensure the given user follows the workspace for quick access listings."""
    if not workspace or not user:
        return
    workspace.followers.add(user)


def _resolve_system_role(role_value: str):
    """Look up the seeded system ``WorkspaceRole`` row matching a legacy role string.

    Returns ``None`` if no system role carries the given slug — callers
    should degrade to null (the legacy ``role`` string stays correct
    regardless). The ``workspace_role`` FK is the new enforcement anchor;
    keeping it in lockstep with the legacy string until Phase 2 means
    RBAC readers can migrate one at a time.
    """
    if not role_value:
        return None
    from infrastructure.persistence.workspaces.models import WorkspaceRole

    return WorkspaceRole.objects.filter(workspace__isnull=True, is_system=True, slug=role_value).first()


def ensure_workspace_membership(workspace, user: CustomUser, role: str | None = None) -> None:
    """Ensure the user has an active membership record for the workspace.

    Never downgrades an existing higher-privilege role. Role hierarchy:
    owner > admin > member > viewer.
    """
    if not workspace or not user:
        return

    _ROLE_RANK = {
        WorkspaceMembership.Role.OWNER: 4,
        WorkspaceMembership.Role.ADMIN: 3,
        WorkspaceMembership.Role.MEMBER: 2,
        WorkspaceMembership.Role.VIEWER: 1,
    }

    is_owner = str(workspace.workspace_owner_id) == str(user.id)
    role_value = role or (WorkspaceMembership.Role.OWNER if is_owner else WorkspaceMembership.Role.MEMBER)

    # Derive persona from ownership + workspace type so the frontend
    # dashboard experience is correct from the very first login.
    if is_owner:
        persona_value = (
            WorkspaceMembership.Persona.PRIVATE
            if getattr(workspace, "workspace_type", None) == "personal"
            else WorkspaceMembership.Persona.ADMIN
        )
    else:
        persona_value = WorkspaceMembership.Persona.CONTRIBUTOR

    system_role = _resolve_system_role(role_value)
    membership, created = WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            "role": role_value,
            "workspace_role": system_role,
            "persona": persona_value,
            "status": WorkspaceMembership.Status.ACTIVE,
            "accepted_at": timezone.now(),
        },
    )
    updates = []
    # Only change role if the new role is higher-privilege than the current one
    current_rank = _ROLE_RANK.get(membership.role, 0)
    new_rank = _ROLE_RANK.get(role_value, 0)
    if not created and new_rank > current_rank:
        membership.role = role_value
        membership.workspace_role = system_role
        updates.extend(["role", "workspace_role"])
    # Backfill workspace_role for rows created before Phase 1b shipped.
    if not created and membership.workspace_role_id is None and system_role is not None:
        membership.workspace_role = system_role
        updates.append("workspace_role")
    # Fix persona for owners whose membership was created before persona
    # was set correctly (model default was "contributor" for everyone).
    if is_owner and membership.persona == WorkspaceMembership.Persona.CONTRIBUTOR:
        membership.persona = persona_value
        updates.append("persona")
    if membership.status != WorkspaceMembership.Status.ACTIVE:
        membership.status = WorkspaceMembership.Status.ACTIVE
        updates.append("status")
    if membership.accepted_at is None:
        membership.accepted_at = timezone.now()
        updates.append("accepted_at")
    if updates:
        membership.save(update_fields=[*updates, "updated_at"])


def ensure_team_membership(team, user: CustomUser, role: str | None = None) -> None:
    """Ensure the user has an active membership record for the team."""
    if not team or not user:
        return
    role_value = role or (
        TeamMembership.Role.LEAD if str(team.created_by_id) == str(user.id) else TeamMembership.Role.EDITOR
    )
    membership, created = TeamMembership.objects.get_or_create(
        team=team,
        user=user,
        defaults={
            "role": role_value,
            "status": TeamMembership.Status.ACTIVE,
        },
    )
    updates = []
    if membership.role != role_value:
        membership.role = role_value
        updates.append("role")
    if membership.status != TeamMembership.Status.ACTIVE:
        membership.status = TeamMembership.Status.ACTIVE
        updates.append("status")
    if updates:
        membership.save(update_fields=[*updates, "updated_at"])


def user_is_workspace_member(user: CustomUser, workspace: Workspace) -> bool:
    """Return True when the user owns or belongs to the workspace's active teams."""
    if not user or not workspace or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    if str(workspace.workspace_owner_id) == str(user.id):
        return True
    if WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=user,
        status=WorkspaceMembership.Status.ACTIVE,
    ).exists():
        return True
    return Team.objects.filter(
        workspace=workspace,
        status=Team.ACTIVE,
        members__id=user.id,
    ).exists()


def user_is_workspace_admin_or_owner(user: CustomUser, workspace: Workspace) -> bool:
    """Return True when the user is the workspace owner or has admin/owner role.

    Admin-level access lets the user interact with every team in the workspace,
    including teams they aren't a member of — notably the seeded Agents team,
    which has only the AI user as a member but must be reachable by workspace
    administrators so they can see AI findings and respond. Reads RBAC via
    ``WorkspaceMembership.role`` per ADR 0002 — never persona.
    """
    if not user or not workspace or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    if str(workspace.workspace_owner_id) == str(user.id):
        return True
    return WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=user,
        status=WorkspaceMembership.Status.ACTIVE,
        role__in=(
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
        ),
    ).exists()


DEFAULT_BOARD_COLUMNS = (
    ("Backlog", 1),
    ("Todo", 2),
    ("In Progress", 3),
    ("Testing", 4),
    ("Complete", 5),
    ("Canceled", 6),
)


def ensure_team_board_columns(workspace, team, owner):
    """Make sure a workspace's primary team has the standard kanban columns."""
    if not team or not workspace:
        return

    for title, order in DEFAULT_BOARD_COLUMNS:
        # Handle duplicates by keeping the first one and deleting others
        existing_columns = Column.objects.filter(
            workspace=workspace,
            team=team,
            title=title,
        ).order_by("id")

        if existing_columns.count() > 1:
            # Keep the first one, delete the rest
            first_column = existing_columns.first()
            existing_columns.exclude(id=first_column.id).delete()
            column = first_column
            created = False
        elif existing_columns.exists():
            column = existing_columns.first()
            created = False
        else:
            column = Column.objects.create(
                workspace=workspace,
                team=team,
                title=title,
                order=order,
                project=None,
                created_by=owner,
            )
            created = True

        updates = []
        if column.order != order:
            column.order = order
            updates.append("order")
        if column.project_id is not None:
            column.project = None
            updates.append("project")
        if owner and column.created_by_id is None:
            column.created_by = owner
            updates.append("created_by")
        if updates:
            column.save(update_fields=updates)

"""Reusable tool mixins for agent classes (ADR 0003).

Mixins compose into agent classes via standard Python multiple
inheritance. Each `@tool`-decorated method on the mixin becomes
available on every agent that mixes it in. Tool names follow
leftmost-MRO-wins de-duplication, so an agent that wants to override a
mixin tool just declares its own `@tool` method with the same name.

Module name starts with `_` so `discover_agents()` skips it — mixins
are library code, not standalone agents.
"""

from __future__ import annotations

from components.agents.infrastructure.adapters.langchain.base import tool


class WorkspaceContextMixin:
    """Tools every workspace-aware agent should have for self-introspection.

    Mix in to give an agent the ability to answer "who am I, where am I,
    what's this workspace?" without re-implementing the lookup in every
    agent class.
    """

    @tool(
        name="whoami",
        description=(
            "Identify the current user and their persona/role in the "
            "active workspace. No input. Output: a short string with "
            "the user's email, persona, and role."
        ),
    )
    def whoami(self) -> str:
        """Return the current user's identity inside the active workspace."""
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
        )

        user = CustomUser.objects.filter(id=self.user_id).first()
        if user is None:
            return "Unknown user."

        ws = Workspace.objects.filter(id=self.workspace_id).first()
        ws_name = (
            getattr(ws, "workspace_name", None) or "(unnamed workspace)"
        )

        membership = WorkspaceMembership.objects.filter(
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).first()
        persona = (membership.persona if membership else "") or "guest"
        role = (membership.role if membership else "") or "viewer"

        full_name = (
            f"{user.first_name or ''} {user.last_name or ''}".strip()
            or user.username
            or user.email
        )
        return (
            f"You are {full_name} ({user.email}), "
            f"in workspace '{ws_name}' as a {persona} with role {role}."
        )

    @tool(
        name="get_workspace_info",
        description=(
            "Get a summary of the current workspace: name, total active "
            "members, total teams, and creation date. No input. Output: "
            "a short string."
        ),
    )
    def get_workspace_info(self) -> str:
        """Return high-level info about the active workspace."""
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceMembership,
        )

        ws = Workspace.objects.filter(id=self.workspace_id).first()
        if ws is None:
            return "Workspace not found."

        member_count = WorkspaceMembership.objects.filter(
            workspace_id=ws.id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).count()
        team_count = ws.workspace_teams.count() if hasattr(ws, "workspace_teams") else 0
        created = ws.created_at.strftime("%Y-%m-%d") if getattr(ws, "created_at", None) else "unknown"

        name = getattr(ws, "workspace_name", None) or "(unnamed)"
        return (
            f"Workspace '{name}' — {member_count} active member"
            f"{'s' if member_count != 1 else ''}, {team_count} team"
            f"{'s' if team_count != 1 else ''}, created {created}."
        )

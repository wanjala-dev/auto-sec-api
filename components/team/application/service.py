"""Application service for the team bounded context.

Orchestration only – delegates to use cases for business logic.
This is the single orchestration entry point for the application layer.

Invitation and membership operations have been extracted to
``components.membership.application.service.MembershipService``.
"""

from __future__ import annotations

from components.shared_kernel.domain.errors import NotFoundError, ValidationError
from dataclasses import dataclass, field

from components.team.application.commands import (
    ActivateTeamContextCommand,
    ActivateWorkspaceContextCommand,
    CreateTeamCommand,
    SyncWorkspaceAiTeammateCommand,
    UpdateTeamCommand,
)
from components.team.application.providers.team_context_provider import (
    TeamContextProvider,
)
from components.team.application.providers.team_management_provider import (
    TeamManagementProvider,
)
from components.membership.application.providers.membership_provider import (
    MembershipProvider,
)


@dataclass
class TeamService:
    """Application service for the team bounded context.

    Orchestration only – delegates to use cases for business logic.
    Covers team CRUD, activation, and AI teammate sync.

    Invitation and membership operations now live in
    ``components.membership.application.service.MembershipService``.

    For backward compatibility, ``query_team_membership()`` delegates to
    the membership context's query service so that team controllers can
    still list teams and retrieve team details.
    """

    team_context_provider: TeamContextProvider = field(
        default_factory=TeamContextProvider
    )
    team_management_provider: TeamManagementProvider = field(
        default_factory=TeamManagementProvider
    )
    membership_provider: MembershipProvider = field(
        default_factory=MembershipProvider
    )

    def activate_team_context(self, command: ActivateTeamContextCommand):
        """Orchestrate team context activation."""
        use_case = self.team_context_provider.build_activate_team_context_use_case()
        return use_case.execute(
            team_id=command.team_id,
            actor_id=command.actor_id,
            is_staff=command.is_staff,
            is_superuser=command.is_superuser,
        )

    def activate_workspace_context(self, command: ActivateWorkspaceContextCommand):
        """Activate a workspace context for the actor, in one round-trip.

        Collapses the legacy two-call flow (``list_workspace_teams`` then
        ``activate_team_context``) into one round-trip. The frontend used
        to fetch teams, pick the first id, and POST it back — which added
        ~1s of visible latency to every workspace switch and opened a
        race window when rapid clicks fired multiple activations.

        When the actor has an accessible team in the workspace, that team
        is activated (sets active_team_id + active_workspace_id). When the
        actor is a workspace member with **no** internal team — e.g. a
        sponsor / viewer (ADR 0002) — the workspace pointer is persisted
        without a team instead of failing. This keeps workspace switching
        team-independent: ``navigate()`` owns the active view on the
        frontend, and this call keeps the server-side active-workspace
        cache (me/summary, AI quota, request routing, cross-session
        bootstrap) coherent for every persona. Returns the activated team,
        or ``None`` for a teamless activation.
        """
        query_service = self.query_team_membership()
        teams, _ = query_service.list_workspace_teams(
            workspace_id=command.workspace_id,
            actor_id=command.actor_id,
            is_staff=command.is_staff,
            is_superuser=command.is_superuser,
        )

        if teams:
            first = teams[0]
            team_id = getattr(first, "id", None)
            if team_id is None and isinstance(first, dict):
                team_id = first.get("id") or first.get("pk")

            if not team_id:
                raise ValidationError("Resolved team has no id.")

            return self.activate_team_context(
                ActivateTeamContextCommand(
                    team_id=team_id,
                    actor_id=command.actor_id,
                    is_staff=command.is_staff,
                    is_superuser=command.is_superuser,
                )
            )

        # No accessible team — a workspace member with no internal team
        # (sponsor / viewer). Verify workspace access, then persist the
        # workspace pointer without a team. Staff/superusers bypass the
        # membership check (they can act in any workspace).
        if not (command.is_staff or command.is_superuser):
            access = self.membership_provider.build_membership_port().check_workspace_access(
                user_id=command.actor_id,
                workspace_id=command.workspace_id,
            )
            if not access.allowed:
                raise NotFoundError("No accessible team in this workspace.")

        self.team_context_provider.build_team_context_port().activate_workspace_for_user(
            actor_id=command.actor_id,
            workspace_id=command.workspace_id,
        )
        return None

    def create_team(self, command: CreateTeamCommand):
        """Orchestrate team creation."""
        use_case = self.team_management_provider.build_create_team_use_case()
        return use_case.execute(
            title=command.title,
            workspace_id=command.workspace_id,
            actor=command.actor,
        )

    def update_team(self, command: UpdateTeamCommand):
        """Orchestrate team update."""
        use_case = self.team_management_provider.build_update_team_use_case()
        return use_case.execute(
            actor=command.actor,
            validated_data=command.validated_data,
            is_staff=command.is_staff,
            is_superuser=command.is_superuser,
        )

    def sync_workspace_ai_teammate(self, command: SyncWorkspaceAiTeammateCommand):
        """Orchestrate workspace AI teammate synchronization."""
        use_case = self.team_management_provider.build_sync_workspace_ai_teammate_use_case()
        return use_case.execute(workspace=command.workspace)

    # ── Cross-context delegation ────────────────────────────────────────
    def query_team_membership(self):
        """Return the membership query service.

        Team controllers need to list teams and retrieve team details.
        That query logic now lives in the membership bounded context;
        this thin delegation keeps the controller call-sites unchanged.
        """
        return self.membership_provider.build_query_service()

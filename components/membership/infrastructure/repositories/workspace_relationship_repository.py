"""ORM adapter implementing ``WorkspaceRelationshipPort``.

All persistence + cross-aggregate wiring lives here. The application layer
depends on the port, not this class. Volunteer/contribute joins delegate
the owner-approval request to the workspace context's join-request use case
(application import — no cross-context infrastructure dependency).
"""

from __future__ import annotations

import logging

from components.membership.application.ports.workspace_relationship_port import (
    TeamJoinOutcome,
    TeamJoinResult,
    WorkspaceRelationshipPort,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceRelationshipRepository(WorkspaceRelationshipPort):
    """Django ORM implementation of the self-service relationship port."""

    def _system_role(self, slug: str):
        from infrastructure.persistence.workspaces.models import WorkspaceRole

        return (
            WorkspaceRole.objects
            .filter(workspace__isnull=True, is_system=True, slug=slug)
            .first()
        )

    def workspace_exists(self, *, workspace_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).exists()

    def add_follower(self, *, workspace_id: str, user_id: str) -> None:
        from infrastructure.persistence.workspaces.models import Workspace

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is not None:
            workspace.followers.add(user_id)

    def active_membership_persona(
        self, *, workspace_id: str, user_id: str
    ) -> str | None:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        membership = (
            WorkspaceMembership.objects
            .filter(
                workspace_id=workspace_id,
                user_id=user_id,
                is_impersonation=False,
                status=WorkspaceMembership.Status.ACTIVE,
            )
            .only("persona")
            .first()
        )
        return membership.persona if membership is not None else None

    def upsert_sponsor_membership(
        self, *, workspace_id: str, user_id: str
    ) -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        viewer_role = self._system_role("viewer")
        membership, created = WorkspaceMembership.objects.get_or_create(
            user_id=user_id,
            workspace_id=workspace_id,
            is_impersonation=False,
            defaults={
                "persona": WorkspaceMembership.Persona.SPONSOR,
                "role": WorkspaceMembership.Role.VIEWER,
                "workspace_role": viewer_role,
                "status": WorkspaceMembership.Status.ACTIVE,
            },
        )
        # Never downgrade a richer existing membership — only reactivate a
        # suspended one and backfill the role FK.
        updates = []
        if not created and membership.status == WorkspaceMembership.Status.SUSPENDED:
            membership.status = WorkspaceMembership.Status.ACTIVE
            updates.append("status")
        if membership.workspace_role_id is None and viewer_role is not None:
            membership.workspace_role = viewer_role
            updates.append("workspace_role")
        if updates:
            membership.save(update_fields=updates)

    def request_team_join(
        self, *, workspace_id: str, user_id: str, persona: str
    ) -> TeamJoinResult:
        from django.db import transaction

        from infrastructure.persistence.workspaces.models import WorkspaceMembership
        from components.workspace.application.ports.workspace_join_request_port import (
            CreateJoinRequestCommand,
        )
        from components.workspace.application.providers.workspace_join_request_provider import (
            get_workspace_join_request_provider,
        )
        from components.workspace.application.use_cases.create_workspace_join_request_use_case import (
            CreateWorkspaceJoinRequestUseCase,
        )
        from components.workspace.domain.errors import (
            JoinRequestAlreadyExistsError,
            JoinRequestValidationError,
            WorkspaceNotFoundError,
        )

        member_role = self._system_role("member")

        def _ensure_pending_membership():
            WorkspaceMembership.objects.get_or_create(
                user_id=user_id,
                workspace_id=workspace_id,
                is_impersonation=False,
                defaults={
                    "persona": persona,
                    "role": WorkspaceMembership.Role.MEMBER,
                    "workspace_role": member_role,
                    "status": WorkspaceMembership.Status.PENDING,
                },
            )

        try:
            with transaction.atomic():
                # Raise the owner-approval request first — this validates the
                # workspace is private/requestable and notifies the owner.
                CreateWorkspaceJoinRequestUseCase(
                    store=get_workspace_join_request_provider().build_store()
                ).execute(
                    CreateJoinRequestCommand(
                        workspace_id=str(workspace_id),
                        requester_id=str(user_id),
                        message="Onboarding join request.",
                        requested_persona=persona,
                    )
                )
                # Land them on the persona dashboard immediately, behind the
                # "pending approval" lock until the owner approves.
                _ensure_pending_membership()
        except JoinRequestAlreadyExistsError:
            # They already requested — make sure the pending membership exists
            # so the FE still lands them behind the lock.
            _ensure_pending_membership()
            return TeamJoinResult(outcome=TeamJoinOutcome.ALREADY_PENDING)
        except (JoinRequestValidationError, WorkspaceNotFoundError) as exc:
            return TeamJoinResult(
                outcome=TeamJoinOutcome.NOT_ALLOWED, detail=str(exc)
            )

        return TeamJoinResult(outcome=TeamJoinOutcome.REQUESTED)

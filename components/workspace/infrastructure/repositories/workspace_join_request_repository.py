"""ORM adapter implementing ``WorkspaceJoinRequestPort``.

All persistence + cross-aggregate wiring lives here. The application
layer depends on the port, not this class.
"""

from __future__ import annotations

import logging

from django.db import router, transaction
from django.utils import timezone

from components.workspace.application.ports.workspace_join_request_port import (
    CreateJoinRequestCommand,
    JoinRequestListResult,
    JoinRequestResult,
    ReviewJoinRequestCommand,
    WithdrawJoinRequestCommand,
    WorkspaceJoinRequestPort,
)
from components.workspace.domain.entities.workspace_join_request_entity import (
    JoinRequestStatus,
    MAX_MESSAGE_LENGTH,
    MAX_REVIEW_NOTE_LENGTH,
)
from components.workspace.domain.errors import (
    JoinRequestAlreadyExistsError,
    JoinRequestNotFoundError,
    JoinRequestValidationError,
    WorkspaceNotFoundError,
)
from components.workspace.domain.policies.join_request_policy_service import (
    JoinRequestPolicyService,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceJoinRequestRepository(WorkspaceJoinRequestPort):
    """Persistence + membership promotion adapter."""

    def __init__(self, policy: JoinRequestPolicyService | None = None) -> None:
        self._policy = policy or JoinRequestPolicyService()

    # ── helpers ──────────────────────────────────────────────────────

    def _get_workspace(self, workspace_id: str):
        from infrastructure.persistence.workspaces.models import Workspace

        try:
            return Workspace.objects.get(pk=workspace_id)
        except Workspace.DoesNotExist as exc:
            raise WorkspaceNotFoundError("Workspace not found.") from exc

    def _get_user(self, user_id: str):
        from infrastructure.persistence.users.models import CustomUser

        try:
            return CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist as exc:
            raise JoinRequestValidationError("User not found.") from exc

    def _is_owner(self, workspace, user_id: str) -> bool:
        return str(workspace.workspace_owner_id) == str(user_id)

    def _is_admin(self, workspace, user_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        return WorkspaceMembership.objects.filter(
            workspace_id=workspace.id,
            user_id=user_id,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=(
                WorkspaceMembership.Role.OWNER,
                WorkspaceMembership.Role.ADMIN,
            ),
        ).exists()

    def _is_member(self, workspace, user_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        return WorkspaceMembership.objects.filter(
            workspace_id=workspace.id,
            user_id=user_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).exists()

    def _serialize(
        self, row, *, membership_id: str | None = None
    ) -> JoinRequestResult:
        requester = row.requester
        reviewer = row.reviewed_by
        reviewer_name = None
        if reviewer is not None:
            reviewer_name = (
                getattr(reviewer, "full_name", None)
                or getattr(reviewer, "get_full_name", lambda: "")()
                or getattr(reviewer, "username", None)
                or getattr(reviewer, "email", None)
            )
        requester_name = (
            getattr(requester, "full_name", None)
            or getattr(requester, "get_full_name", lambda: "")()
            or getattr(requester, "username", None)
            or getattr(requester, "email", "")
        )
        return JoinRequestResult(
            request_id=str(row.id),
            workspace_id=str(row.workspace_id),
            workspace_name=row.workspace.workspace_name or "",
            requester_id=str(row.requester_id),
            requester_name=requester_name or "",
            requester_email=getattr(requester, "email", "") or "",
            status=row.status,
            message=row.message or "",
            requested_at=row.requested_at.isoformat() if row.requested_at else "",
            reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
            reviewed_by_id=str(row.reviewed_by_id) if row.reviewed_by_id else None,
            reviewed_by_name=reviewer_name,
            review_note=row.review_note or "",
            membership_id=membership_id,
        )

    # ── port methods ─────────────────────────────────────────────────

    def create_request(
        self, *, command: CreateJoinRequestCommand
    ) -> JoinRequestResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
        )

        workspace = self._get_workspace(command.workspace_id)
        self._policy.ensure_workspace_is_requestable(
            workspace_privacy=workspace.privacy,
            workspace_is_active=bool(workspace.is_active),
        )

        self._policy.ensure_can_request(
            requester_is_owner=self._is_owner(workspace, command.requester_id),
            requester_is_member=self._is_member(workspace, command.requester_id),
            has_pending_request=WorkspaceJoinRequest.objects.filter(
                workspace_id=workspace.id,
                requester_id=command.requester_id,
                status=JoinRequestStatus.PENDING,
            ).exists(),
        )

        message = (command.message or "").strip()
        if len(message) > MAX_MESSAGE_LENGTH:
            raise JoinRequestValidationError(
                f"Message too long (max {MAX_MESSAGE_LENGTH} characters)."
            )

        requester = self._get_user(command.requester_id)

        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        requested_persona = (
            command.requested_persona
            or WorkspaceMembership.Persona.CONTRIBUTOR
        )
        valid_personas = {
            WorkspaceMembership.Persona.CONTRIBUTOR,
            WorkspaceMembership.Persona.VOLUNTEER,
        }
        if requested_persona not in valid_personas:
            requested_persona = WorkspaceMembership.Persona.CONTRIBUTOR

        try:
            row = WorkspaceJoinRequest.objects.create(
                workspace=workspace,
                requester=requester,
                message=message,
                requested_persona=requested_persona,
                status=JoinRequestStatus.PENDING,
            )
        except Exception as exc:  # noqa: BLE001
            # The unique partial index may race — surface as a 409.
            if "uniq_pending_workspace_join_request" in str(exc):
                raise JoinRequestAlreadyExistsError(
                    "You already have a pending join request for this workspace."
                ) from exc
            raise

        # Emit domain event — notification handler converts to in-app/email.
        from components.workspace.domain.events.workspace_join_request_events import (
            WorkspaceJoinRequestCreated,
        )
        from components.workspace.infrastructure.adapters.join_request_notification_adapter import (
            JoinRequestNotificationAdapter,
        )

        event = WorkspaceJoinRequestCreated(
            request_id=row.id,
            workspace_id=workspace.id,
            requester_id=requester.id,
            message=message,
            requested_at=row.requested_at or timezone.now(),
        )
        transaction.on_commit(
            lambda: JoinRequestNotificationAdapter().notify_created(
                event=event,
                workspace=workspace,
                requester=requester,
            )
        )

        return self._serialize(row)

    def approve_request(
        self, *, command: ReviewJoinRequestCommand
    ) -> JoinRequestResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
            WorkspaceMembership,
        )

        note = (command.note or "").strip()
        if len(note) > MAX_REVIEW_NOTE_LENGTH:
            raise JoinRequestValidationError(
                f"Review note too long (max {MAX_REVIEW_NOTE_LENGTH} characters)."
            )

        # Route the atomic to the tenant DB the model lives on (TenantRouter); a bare atomic() only covers 'default' and select_for_update would fail. See donation_payment_repository.py for the same fix.
        db_alias = router.db_for_write(WorkspaceJoinRequest)
        with transaction.atomic(using=db_alias):
            try:
                row = (
                    WorkspaceJoinRequest.objects.using(db_alias).select_for_update()
                    .select_related("workspace", "requester")
                    .get(pk=command.request_id)
                )
            except WorkspaceJoinRequest.DoesNotExist as exc:
                raise JoinRequestNotFoundError("Join request not found.") from exc

            workspace = row.workspace
            self._policy.ensure_can_review(
                reviewer_is_owner=self._is_owner(workspace, command.reviewer_id),
                reviewer_is_admin=self._is_admin(workspace, command.reviewer_id),
                reviewer_is_staff=bool(
                    command.reviewer_is_staff or command.reviewer_is_superuser
                ),
            )

            if row.status != JoinRequestStatus.PENDING:
                raise JoinRequestValidationError(
                    f"Cannot approve a join request in status '{row.status}'."
                )

            reviewer = self._get_user(command.reviewer_id)

            row.status = JoinRequestStatus.APPROVED
            row.reviewed_at = timezone.now()
            row.reviewed_by = reviewer
            row.review_note = note
            row.save(
                update_fields=[
                    "status",
                    "reviewed_at",
                    "reviewed_by",
                    "review_note",
                    "updated_at",
                ]
            )

            # Double-write the new workspace_role FK. Legacy `role` string
            # stays the authoritative value until Phase 2 enforcement migrates.
            from infrastructure.persistence.workspaces.models import WorkspaceRole

            member_system_role = (
                WorkspaceRole.objects
                .filter(workspace__isnull=True, is_system=True, slug="member")
                .first()
            )
            # The requester asked for a specific team experience (contributor
            # vs volunteer); honor it so the two personas stay distinct. A
            # self-service onboarding join already created a PENDING membership
            # with this persona — approval just flips it ACTIVE.
            approved_persona = (
                row.requested_persona
                or WorkspaceMembership.Persona.CONTRIBUTOR
            )
            membership, _created = WorkspaceMembership.objects.get_or_create(
                workspace=workspace,
                user=row.requester,
                defaults={
                    "role": WorkspaceMembership.Role.MEMBER,
                    "workspace_role": member_system_role,
                    "persona": approved_persona,
                    "status": WorkspaceMembership.Status.ACTIVE,
                    "invited_by": reviewer,
                    "accepted_at": timezone.now(),
                },
            )
            reactivate_updates = []
            if membership.status != WorkspaceMembership.Status.ACTIVE:
                membership.status = WorkspaceMembership.Status.ACTIVE
                membership.accepted_at = timezone.now()
                reactivate_updates.extend(["status", "accepted_at"])
            if membership.persona != approved_persona:
                membership.persona = approved_persona
                reactivate_updates.append("persona")
            if membership.workspace_role_id is None and member_system_role is not None:
                membership.workspace_role = member_system_role
                reactivate_updates.append("workspace_role")
            if reactivate_updates:
                membership.save(update_fields=reactivate_updates)

        from components.workspace.domain.events.workspace_join_request_events import (
            WorkspaceJoinRequestApproved,
        )
        from components.workspace.infrastructure.adapters.join_request_notification_adapter import (
            JoinRequestNotificationAdapter,
        )

        event = WorkspaceJoinRequestApproved(
            request_id=row.id,
            workspace_id=workspace.id,
            requester_id=row.requester_id,
            reviewer_id=reviewer.id,
            approved_at=row.reviewed_at,
            note=note,
        )
        transaction.on_commit(
            lambda: JoinRequestNotificationAdapter().notify_approved(
                event=event,
                workspace=workspace,
                requester=row.requester,
                reviewer=reviewer,
            )
        )

        return self._serialize(row, membership_id=str(membership.id))

    def deny_request(
        self, *, command: ReviewJoinRequestCommand
    ) -> JoinRequestResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
        )

        note = (command.note or "").strip()
        if len(note) > MAX_REVIEW_NOTE_LENGTH:
            raise JoinRequestValidationError(
                f"Review note too long (max {MAX_REVIEW_NOTE_LENGTH} characters)."
            )

        # Route the atomic to the tenant DB the model lives on (TenantRouter); a bare atomic() only covers 'default' and select_for_update would fail. See donation_payment_repository.py for the same fix.
        db_alias = router.db_for_write(WorkspaceJoinRequest)
        with transaction.atomic(using=db_alias):
            try:
                row = (
                    WorkspaceJoinRequest.objects.using(db_alias).select_for_update()
                    .select_related("workspace", "requester")
                    .get(pk=command.request_id)
                )
            except WorkspaceJoinRequest.DoesNotExist as exc:
                raise JoinRequestNotFoundError("Join request not found.") from exc

            workspace = row.workspace
            self._policy.ensure_can_review(
                reviewer_is_owner=self._is_owner(workspace, command.reviewer_id),
                reviewer_is_admin=self._is_admin(workspace, command.reviewer_id),
                reviewer_is_staff=bool(
                    command.reviewer_is_staff or command.reviewer_is_superuser
                ),
            )

            if row.status != JoinRequestStatus.PENDING:
                raise JoinRequestValidationError(
                    f"Cannot deny a join request in status '{row.status}'."
                )

            reviewer = self._get_user(command.reviewer_id)

            row.status = JoinRequestStatus.DENIED
            row.reviewed_at = timezone.now()
            row.reviewed_by = reviewer
            row.review_note = note
            row.save(
                update_fields=[
                    "status",
                    "reviewed_at",
                    "reviewed_by",
                    "review_note",
                    "updated_at",
                ]
            )

        from components.workspace.domain.events.workspace_join_request_events import (
            WorkspaceJoinRequestDenied,
        )
        from components.workspace.infrastructure.adapters.join_request_notification_adapter import (
            JoinRequestNotificationAdapter,
        )

        event = WorkspaceJoinRequestDenied(
            request_id=row.id,
            workspace_id=workspace.id,
            requester_id=row.requester_id,
            reviewer_id=reviewer.id,
            denied_at=row.reviewed_at,
            note=note,
        )
        transaction.on_commit(
            lambda: JoinRequestNotificationAdapter().notify_denied(
                event=event,
                workspace=workspace,
                requester=row.requester,
                reviewer=reviewer,
            )
        )

        return self._serialize(row)

    def withdraw_request(
        self, *, command: WithdrawJoinRequestCommand
    ) -> JoinRequestResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
        )

        # Route the atomic to the tenant DB the model lives on (TenantRouter); a bare atomic() only covers 'default' and select_for_update would fail. See donation_payment_repository.py for the same fix.
        db_alias = router.db_for_write(WorkspaceJoinRequest)
        with transaction.atomic(using=db_alias):
            try:
                row = (
                    WorkspaceJoinRequest.objects.using(db_alias).select_for_update()
                    .select_related("workspace", "requester")
                    .get(pk=command.request_id)
                )
            except WorkspaceJoinRequest.DoesNotExist as exc:
                raise JoinRequestNotFoundError("Join request not found.") from exc

            self._policy.ensure_can_withdraw(
                requester_id=str(row.requester_id),
                actor_id=str(command.actor_id),
            )

            if row.status != JoinRequestStatus.PENDING:
                raise JoinRequestValidationError(
                    f"Cannot withdraw a join request in status '{row.status}'."
                )

            row.status = JoinRequestStatus.WITHDRAWN
            row.reviewed_at = timezone.now()
            row.save(update_fields=["status", "reviewed_at", "updated_at"])

        return self._serialize(row)

    def list_pending_for_workspace(
        self,
        *,
        workspace_id: str,
        actor_id: str,
        actor_is_staff: bool = False,
        actor_is_superuser: bool = False,
    ) -> JoinRequestListResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
        )

        workspace = self._get_workspace(workspace_id)

        self._policy.ensure_can_review(
            reviewer_is_owner=self._is_owner(workspace, actor_id),
            reviewer_is_admin=self._is_admin(workspace, actor_id),
            reviewer_is_staff=bool(actor_is_staff or actor_is_superuser),
        )

        rows = (
            WorkspaceJoinRequest.objects.filter(
                workspace_id=workspace_id,
                status=JoinRequestStatus.PENDING,
            )
            .select_related("workspace", "requester", "reviewed_by")
            .order_by("-requested_at")
        )
        items = [self._serialize(row) for row in rows]
        return JoinRequestListResult(items=items, total=len(items))

    def list_mine(self, *, requester_id: str) -> JoinRequestListResult:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceJoinRequest,
        )

        rows = (
            WorkspaceJoinRequest.objects.filter(requester_id=requester_id)
            .select_related("workspace", "requester", "reviewed_by")
            .order_by("-requested_at")
        )
        items = [self._serialize(row) for row in rows]
        return JoinRequestListResult(items=items, total=len(items))

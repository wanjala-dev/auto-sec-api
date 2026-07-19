"""Use case: process a full batch of invitations.

Extracted from ``components.team.application.use_cases.process_team_invitation_batch_use_case``.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.membership.application.use_cases.issue_invitation_use_case import (
    IssueInvitationUseCase,
)
from components.membership.application.use_cases.prepare_invitation_use_case import (
    PrepareInvitationUseCase,
)
from components.workspace.application.use_cases.register_invited_user_use_case import (
    RegisterInvitedUserUseCase,
)
from components.membership.application.use_cases.invitation_notification_use_case import (
    InvitationNotificationUseCase,
)


@dataclass(frozen=True)
class ProcessedInvitationBatchResult:
    message: str
    results: dict


@dataclass
class ProcessInvitationBatchUseCase:
    prepare_use_case: PrepareInvitationUseCase
    issue_use_case: IssueInvitationUseCase
    register_use_case: RegisterInvitedUserUseCase
    notification_use_case: InvitationNotificationUseCase

    def execute(
        self,
        *,
        actor,
        workspace_id,
        team_id,
        emails: list[str] | None = None,
        user_ids: list | None = None,
        request=None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> ProcessedInvitationBatchResult:
        batch = self.prepare_use_case.execute(
            workspace_id=workspace_id,
            team_id=team_id,
            actor=actor,
            emails=emails or [],
            user_ids=user_ids or [],
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

        results = {
            "added": [],
            "skipped": [],
            "missing": [{"user_id": user_id} for user_id in batch.missing_user_ids],
        }

        for user_obj in batch.existing_users:
            self._issue_for_existing_user(
                user_obj=user_obj,
                workspace=batch.workspace,
                team=batch.team,
                actor_id=actor.id,
                request=request,
                results=results,
            )

        for email in batch.new_emails:
            self._issue_for_new_email(
                email=email,
                workspace=batch.workspace,
                team=batch.team,
                actor_id=actor.id,
                request=request,
                results=results,
            )

        total_targets = len(batch.existing_users) + len(batch.new_emails)
        message = "User invited successfully!" if total_targets == 1 and results["added"] else "Invites processed."
        return ProcessedInvitationBatchResult(
            message=message,
            results=results,
        )

    def _issue_for_existing_user(
        self,
        *,
        user_obj,
        workspace,
        team,
        actor_id,
        request,
        results: dict,
    ) -> None:
        email = (user_obj.email or "").strip().lower()
        if not email:
            results["skipped"].append(
                {"user_id": str(user_obj.id), "reason": "missing_email"}
            )
            return

        issue_result = self.issue_use_case.execute(
            workspace=workspace,
            team=team,
            invitee=user_obj,
            email=email,
            actor_id=actor_id,
        )
        if issue_result.status != "added":
            results["skipped"].append(
                {"user_id": str(user_obj.id), "email": email, "reason": issue_result.reason}
            )
            return

        self.notification_use_case.handle_invitation_issued(
            invitation=issue_result.invitation,
            invited_user=user_obj,
            actor_id=actor_id,
            request=request,
        )
        results["added"].append({"user_id": str(user_obj.id), "email": email})

    def _issue_for_new_email(
        self,
        *,
        email: str,
        workspace,
        team,
        actor_id,
        request,
        results: dict,
    ) -> None:
        invited_user = self.register_use_case.execute(
            email=email,
            name=email.split("@")[0],
            request=request,
            team_name=team.title,
            workspace_id=workspace.id,
        )

        issue_result = self.issue_use_case.execute(
            workspace=workspace,
            team=team,
            invitee=invited_user,
            email=email,
            actor_id=actor_id,
        )
        if issue_result.status != "added":
            results["skipped"].append(
                {"user_id": str(invited_user.id), "email": email, "reason": issue_result.reason}
            )
            return

        self.notification_use_case.handle_invitation_issued(
            invitation=issue_result.invitation,
            invited_user=invited_user,
            actor_id=actor_id,
            request=request,
        )
        results["added"].append({"user_id": str(invited_user.id), "email": email})

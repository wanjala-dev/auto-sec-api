from __future__ import annotations

import secrets
import string

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from components.membership.application.ports.team_membership_port import TeamMembershipPort
from components.membership.domain.errors import (
    InvitationValidationError,
    MembershipAuthorizationError,
    MembershipValidationError,
    WorkspaceAdminRequiredError,
)
from infrastructure.persistence.team.models import Invitation, Team, TeamMembership
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


class OrmInvitationRepository:
    def __init__(self, *, team_membership_store: TeamMembershipPort) -> None:
        self.team_membership_store = team_membership_store

    def issue_invitation(self, *, workspace, team, invitee, email: str, actor_id):
        if team.members.filter(id=invitee.id).exists():
            return {"status": "skipped", "email": email, "invitee": invitee, "reason": "already_member"}

        invitation = Invitation.objects.filter(email=email, team=team, workspace=workspace).first()
        if invitation:
            return {
                "status": "skipped",
                "email": email,
                "invitee": invitee,
                "reason": "already_invited",
                "invitation": invitation,
            }

        invitation = Invitation.objects.create(
            workspace=workspace,
            team=team,
            email=email,
            code=self._generate_unique_invite_code(),
        )
        self.team_membership_store.enroll_user_in_team(invitee, workspace, team, update_active_context=False)
        return {"status": "added", "email": email, "invitee": invitee, "invitation": invitation}

    def prepare_invitation_batch(
        self, *, workspace_id, team_id, actor, normalized_emails, user_ids, is_staff=False, is_superuser=False
    ):
        workspace = self._get_workspace(workspace_id)
        if not self._is_workspace_admin(actor=actor, workspace=workspace, is_staff=is_staff, is_superuser=is_superuser):
            raise WorkspaceAdminRequiredError("Only workspace admins can invite members to the team")

        team = self._resolve_team(
            workspace=workspace, team_id=team_id, actor=actor, is_staff=is_staff, is_superuser=is_superuser
        )

        users_by_id = list(CustomUser.objects.filter(id__in=user_ids))
        user_id_lookup = {user.id: user for user in users_by_id}
        missing_user_ids = [str(user_id) for user_id in user_ids if user_id not in user_id_lookup]

        email_query = None
        for email in normalized_emails:
            clause = self._email_clause(email)
            email_query = clause if email_query is None else email_query | clause
        email_users = list(CustomUser.objects.filter(email_query)) if email_query is not None else []
        email_user_lookup = {user.email.lower(): user for user in email_users if user.email}

        target_users = {}
        for user in users_by_id:
            target_users[user.id] = user
        for email in normalized_emails:
            user = email_user_lookup.get(email)
            if user:
                target_users.setdefault(user.id, user)

        new_emails = [email for email in normalized_emails if email not in email_user_lookup]

        self._validate_team_capacity(team=team, existing_users=list(target_users.values()), new_emails=new_emails)

        return {
            "workspace": workspace,
            "team": team,
            "existing_users": list(target_users.values()),
            "new_emails": new_emails,
            "missing_user_ids": missing_user_ids,
        }

    def accept_invitation(self, *, code: str, actor):
        invitation = (
            Invitation.objects.select_related("team", "team__workspace", "workspace")
            .filter(code=code)
            .order_by("-date_sent")
            .first()
        )
        if not invitation:
            raise InvitationValidationError("Invalid or expired invite code.")

        actor_email = (getattr(actor, "email", "") or "").lower()
        invitation_email = (invitation.email or "").lower()
        if invitation_email and invitation_email != actor_email:
            raise MembershipAuthorizationError("This invite code is tied to a different email address.")

        now = timezone.now()
        updates = []
        if invitation.status != Invitation.ACCEPTED:
            invitation.status = Invitation.ACCEPTED
            updates.append("status")
        if not invitation.accepted_at:
            invitation.accepted_at = now
            updates.append("accepted_at")
        if updates:
            invitation.save(update_fields=updates)

        team = invitation.team
        if not team:
            raise ObjectDoesNotExist("Team not found.")

        self.team_membership_store.enroll_user_in_team(actor, invitation.workspace, team, update_active_context=False)
        return invitation

    @staticmethod
    def _email_clause(email: str):
        from django.db.models import Q

        return Q(email__iexact=email)

    @staticmethod
    def _get_workspace(workspace_id):
        if not workspace_id:
            raise MembershipValidationError("Workspace is required.")
        try:
            return Workspace.objects.get(id=workspace_id)
        except Workspace.DoesNotExist as exc:
            raise ObjectDoesNotExist("Workspace not found.") from exc

    def _resolve_team(self, *, workspace, team_id, actor, is_staff=False, is_superuser=False):
        if team_id:
            team = Team.objects.filter(id=team_id, status=Team.ACTIVE, workspace=workspace).first()
            if not team or not self._is_team_lead(actor=actor, team=team, is_staff=is_staff, is_superuser=is_superuser):
                raise MembershipAuthorizationError("Only team leads can invite members to the team")
            return team

        team = self.team_membership_store.get_or_create_default_team(workspace)
        if not team:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured("Unable to locate the default team for this workspace. Please try again later.")
        return team

    @staticmethod
    def _is_workspace_admin(*, actor, workspace, is_staff=False, is_superuser=False):
        if is_staff or is_superuser:
            return True
        if str(workspace.workspace_owner_id) == str(getattr(actor, "id", None)):
            return True
        return WorkspaceMembership.objects.filter(
            workspace=workspace,
            user=actor,
            status=WorkspaceMembership.Status.ACTIVE,
            role__in=[WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN],
        ).exists()

    @staticmethod
    def _is_team_lead(*, actor, team, is_staff=False, is_superuser=False):
        if is_staff or is_superuser:
            return True
        if str(team.workspace.workspace_owner_id) == str(getattr(actor, "id", None)):
            return True
        if str(team.created_by_id) == str(getattr(actor, "id", None)):
            return True
        return TeamMembership.objects.filter(
            team=team,
            user=actor,
            status=TeamMembership.Status.ACTIVE,
            role=TeamMembership.Role.LEAD,
        ).exists()

    @staticmethod
    def _validate_team_capacity(*, team, existing_users, new_emails):
        # Seat-entitlement enforcement was removed along with the subscription
        # domain in this fork. Team invitations are no longer capacity-capped.
        return None

    @staticmethod
    def _generate_code(length):
        return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

    def _generate_unique_invite_code(self, length=6):
        if length < 4:
            length = 4
        code = self._generate_code(length)
        attempts = 0
        while Invitation.objects.filter(code=code).exists():
            attempts += 1
            if attempts > 5 and length < 10:
                length += 1
            code = self._generate_code(length)
        return code

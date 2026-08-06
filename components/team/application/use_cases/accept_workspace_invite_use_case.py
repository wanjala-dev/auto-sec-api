"""Use case for accepting a magic-link workspace invitation.

Validates the token, creates / activates the user account, sets the password
the invitee just chose, writes the active WorkspaceMembership row with the
invited persona + role, and (for team-attached personas) enrolls them in the
target team. Returns JWT tokens so the frontend can drop them straight into
the persona's dashboard.

Permissions: this endpoint is intentionally unauthenticated — the magic-link
token IS the credential. The token is single-use and time-bound (24h).

Ownership boundaries (architecture-manifesto Rule 2 / architecture-skill C2):
the ``CustomUser``/``UserProfile`` write is owned by ``identity`` (via
``InviteUserProvisioningPort``); the ``WorkspaceMembership``/``WorkspaceRole``/
``WorkspaceGroup*`` write is owned by ``workspace`` (via
``WorkspaceMembershipWritePort``); the ``Invitation`` write is own-context (via
``InvitationStorePort``). Team enrollment for team-attached invitations goes
through the team-owned ``InviteTeamEnrollmentPort`` (the #60 root fix — the
original inline enrollment ImportError'd on a renamed class and was silently
swallowed, leaving persona-invite team enrollment a dead no-op). This use case
orchestrates them under one ``atomic()`` and holds no ORM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from components.shared_kernel.application.transactional import atomic
from components.team.application.ports.invitation_store_port import InvitationStorePort
from components.team.application.ports.invite_team_enrollment_port import (
    InviteTeamEnrollmentPort,
)
from components.team.application.ports.invite_token_port import InviteTokenPort
from components.team.application.ports.invite_user_provisioning_port import (
    InviteUserProvisioningPort,
)
from components.team.application.ports.workspace_membership_write_port import (
    WorkspaceMembershipWritePort,
)


def _utc_now():
    """Stdlib replacement for ``django.utils.timezone.now`` (UTC, tz-aware)."""
    return datetime.now(UTC)


def _ensure_aware(value):
    """Stdlib replacement for ``django.utils.timezone.make_aware``."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@dataclass(frozen=True)
class AcceptWorkspaceInviteCommand:
    token: str
    password: str = ""
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True)
class AcceptWorkspaceInviteResult:
    payload: dict | None = None
    error: str | None = None
    status_code: int = 200


@dataclass
class AcceptWorkspaceInviteUseCase:
    invitations: InvitationStorePort
    user_provisioning: InviteUserProvisioningPort
    membership_write: WorkspaceMembershipWritePort
    tokens: InviteTokenPort
    team_enrollment: InviteTeamEnrollmentPort

    def execute(self, command: AcceptWorkspaceInviteCommand) -> AcceptWorkspaceInviteResult:
        if not command.token:
            return AcceptWorkspaceInviteResult(
                error="token is required.",
                status_code=400,
            )

        invitation = self.invitations.find_by_token(token=command.token)
        if invitation is None:
            return AcceptWorkspaceInviteResult(
                error="Invalid or expired invitation link.",
                status_code=404,
            )

        # Look up the user up-front so we can decide whether a password is
        # required. Established users (already have a usable password) can accept
        # by clicking the link — they keep their existing password. Brand-new
        # placeholders MUST set one as part of accept.
        probe = self.user_provisioning.probe(email=invitation.email)
        is_existing_user = probe.established

        if not is_existing_user:
            # New user → password is required (this is their signup).
            if not command.password:
                return AcceptWorkspaceInviteResult(
                    error="Password is required to set up your account.",
                    status_code=400,
                )
            if len(command.password) < 8:
                return AcceptWorkspaceInviteResult(
                    error="Password must be at least 8 characters.",
                    status_code=400,
                )
        elif command.password and len(command.password) < 8:
            # Existing user supplied a password — only enforce length so an
            # empty / blank field still routes to the no-password branch
            # (single-source-of-truth: the established password).
            return AcceptWorkspaceInviteResult(
                error="Password must be at least 8 characters.",
                status_code=400,
            )

        now = _utc_now()
        if invitation.status != InvitationStorePort.STATUS_INVITED:
            return AcceptWorkspaceInviteResult(
                error="This invitation has already been used or revoked.",
                status_code=409,
            )
        # _utc_now() is tz-aware, but with USE_TZ=False the ORM hands back NAIVE
        # datetimes (TIME_ZONE='UTC', so naive == UTC). Normalize the stored
        # expiry through _ensure_aware before comparing — a bare `expires_at <
        # now` raises "can't compare offset-naive and offset-aware datetimes".
        if invitation.expires_at and _ensure_aware(invitation.expires_at) < now:
            self.invitations.mark_expired(invitation_id=invitation.id)
            return AcceptWorkspaceInviteResult(
                error="This invitation has expired. Ask the inviter for a new link.",
                status_code=410,
            )

        with atomic():
            # ``seed_is_contributor`` is only True when this invitation actually
            # carries the contributor persona. For admin / sponsor / auditor
            # invites, leaving it False keeps the global signal honest.
            seed_is_contributor = invitation.persona == "contributor"

            # Provision (get-or-create + activate) the user — identity owns the
            # write. is_contributor promotion happens AFTER the membership
            # decision below (preserving the original guard order).
            provisioned = self.user_provisioning.provision_for_accept(
                email=invitation.email,
                seed_is_contributor=seed_is_contributor,
                password=command.password,
                first_name=command.first_name,
                last_name=command.last_name,
                active_workspace_id=invitation.workspace_id,
                active_team_id=invitation.team_id,
            )
            user_id = provisioned.user_id

            # If the user is already an active member of this workspace, the new
            # invitation is a no-op for role/persona — just consume the token and
            # never touch their existing (possibly stronger) membership. This is
            # what stops an owner being downgraded by accepting a stray invite.
            membership_probe = self.membership_write.probe_membership(
                workspace_id=invitation.workspace_id,
                user_id=user_id,
            )
            preserving_existing_membership = membership_probe.active

            # Promote is_contributor to True ONLY for contributor invites, and
            # only when attaching a NEW membership. When preserving an existing
            # membership the global flag stays untouched (the promotion adapter
            # is itself idempotent + a no-op when already set).
            if seed_is_contributor and not preserving_existing_membership:
                self.user_provisioning.promote_contributor(user_id=user_id)

            # Write the persona + role membership row (or refresh accepted_at
            # when preserving) + enroll into permission groups — workspace owns
            # these models.
            self.membership_write.write_membership(
                workspace_id=invitation.workspace_id,
                user_id=user_id,
                persona=invitation.persona,
                role=invitation.role,
                invited_by_id=invitation.invited_by_id,
                accepted_at=now,
                preserving_existing_membership=preserving_existing_membership,
                permission_group_ids=list(invitation.permission_group_ids or []),
            )

            # Team enrollment (the #60 root fix). The original inline enrollment
            # imported a renamed class (``TeamMembershipRepository`` →
            # ``OrmTeamMembershipRepository``); the ImportError was swallowed by
            # a bare ``except Exception: pass``, so team-attached invites never
            # actually enrolled anyone. Restored here through the team-owned
            # ``InviteTeamEnrollmentPort``: a missing team/workspace is a logged
            # no-op inside the adapter (an invite can outlive its team; the
            # membership row above must still land), real errors propagate.
            # ``mark_contributor`` follows the accept flow's own persona rule
            # (only a contributor invite touches the global ``is_contributor``
            # flag) rather than the legacy repository default of always-True.
            if invitation.team_id:
                self.team_enrollment.enroll(
                    user_id=str(user_id),
                    workspace_id=str(invitation.workspace_id),
                    team_id=str(invitation.team_id),
                    mark_contributor=seed_is_contributor,
                )

            # Issue JWT tokens INSIDE the atomic block so any failure here rolls
            # back the user/membership/invitation writes together.
            issued = self.tokens.issue_for_user(user_id=user_id)

            self.invitations.mark_accepted(invitation_id=invitation.id, accepted_at=now)

        return AcceptWorkspaceInviteResult(
            payload={
                "user_id": user_id,
                "email": invitation.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "workspace_id": invitation.workspace_id,
                "access": issued.access,
                "refresh": issued.refresh,
                "is_existing_user": is_existing_user,
            },
            status_code=200,
        )

"""Use case for accepting a magic-link workspace invitation.

Validates the token, creates / activates the user account, sets the password
the invitee just chose, writes the active WorkspaceMembership row with the
invited persona + role, and (for team-attached personas) enrolls them in the
target team. Returns JWT tokens so the frontend can drop them straight into
the persona's dashboard.

Permissions: this endpoint is intentionally unauthenticated — the magic-link
token IS the credential. The token is single-use and time-bound (24h).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone
from components.shared_kernel.application.transactional import atomic

def _utc_now():
    """Stdlib replacement for ``django.utils.timezone.now`` (UTC, tz-aware)."""
    return datetime.now(timezone.utc)


def _ensure_aware(value):
    """Stdlib replacement for ``django.utils.timezone.make_aware``."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _is_aware(value):
    """Stdlib replacement for ``django.utils.timezone.is_aware``."""
    return value.tzinfo is not None




@dataclass(frozen=True)
class AcceptWorkspaceInviteCommand:
    token: str
    password: str = ""
    first_name: Optional[str] = None
    last_name: Optional[str] = None


@dataclass(frozen=True)
class AcceptWorkspaceInviteResult:
    payload: dict | None = None
    error: str | None = None
    status_code: int = 200


@dataclass
class AcceptWorkspaceInviteUseCase:
    def execute(self, command: AcceptWorkspaceInviteCommand) -> AcceptWorkspaceInviteResult:
        from infrastructure.persistence.team.models import Invitation
        from infrastructure.persistence.users.models import CustomUser, UserProfile
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        if not command.token:
            return AcceptWorkspaceInviteResult(
                error="token is required.",
                status_code=400,
            )

        invitation = Invitation.objects.select_related("workspace", "team").filter(
            token=command.token
        ).first()
        if invitation is None:
            return AcceptWorkspaceInviteResult(
                error="Invalid or expired invitation link.",
                status_code=404,
            )

        # Look up the user up-front so we can decide whether a password
        # is required. Established users (already have a usable password)
        # can accept by clicking the link — they keep their existing
        # password. Brand-new placeholders MUST set one as part of accept.
        existing_user = CustomUser.objects.filter(
            email=invitation.email
        ).first()
        is_existing_user = (
            existing_user is not None and existing_user.has_usable_password()
        )

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
            # Existing user supplied a password — only enforce length so
            # an empty / blank field still routes to the no-password
            # branch (single-source-of-truth: the established password).
            return AcceptWorkspaceInviteResult(
                error="Password must be at least 8 characters.",
                status_code=400,
            )

        # _utc_now() is tz-aware, but with USE_TZ=False the ORM hands back
        # NAIVE datetimes (TIME_ZONE='UTC', so naive == UTC). Normalize the
        # stored expiry through _ensure_aware before comparing — a bare
        # `expires_at < now` raises "can't compare offset-naive and
        # offset-aware datetimes" and 500s every invite accept.
        now = _utc_now()
        if invitation.status != Invitation.INVITED:
            return AcceptWorkspaceInviteResult(
                error="This invitation has already been used or revoked.",
                status_code=409,
            )
        if invitation.expires_at and _ensure_aware(invitation.expires_at) < now:
            invitation.status = Invitation.EXPIRED
            invitation.save(update_fields=["status"])
            return AcceptWorkspaceInviteResult(
                error="This invitation has expired. Ask the inviter for a new link.",
                status_code=410,
            )

        with atomic():
            # ``is_contributor`` is only seeded True when this invitation
            # actually carries the contributor persona. For admin /
            # sponsor / auditor invites, leaving the flag at its default
            # (False) keeps the global signal honest.
            seed_is_contributor = invitation.persona == "contributor"
            user, created = CustomUser.objects.get_or_create(
                email=invitation.email,
                defaults={
                    "username": invitation.email,
                    "is_active": True,
                    "is_verified": True,
                    "is_onboard_complete": True,
                    "is_contributor": seed_is_contributor,
                },
            )
            # Resolve the existing-membership guard up-front so the
            # user-flag write below knows whether we're attaching a new
            # membership or preserving an existing one. If the user is
            # already an active member of this workspace, the new
            # invitation is a no-op — no role/persona/is_contributor
            # touching, just consume the token.
            existing_membership = (
                WorkspaceMembership.objects
                .filter(
                    workspace_id=invitation.workspace_id,
                    user_id=user.id,
                )
                .first()
            )
            preserving_existing_membership = bool(
                existing_membership
                and existing_membership.status
                == WorkspaceMembership.Status.ACTIVE
            )

            # Only set a password when one was actually supplied. For an
            # existing established user accepting via the new "Accept
            # Invite" button, password is empty and we must NOT clobber
            # their existing credential. For a new user signing up via
            # the magic link, password is mandatory (validated above).
            if command.password:
                user.set_password(command.password)
            user.is_active = True
            user.is_verified = True
            user.is_onboard_complete = True
            # Promote ``is_contributor`` to True ONLY for contributor
            # invites, and only when we're actually attaching a NEW
            # membership. If we're preserving an existing membership
            # (e.g. an owner accepting a stray contributor invite), the
            # global flag stays untouched — the user's existing state
            # on this workspace is what counts.
            if (
                seed_is_contributor
                and not preserving_existing_membership
                and not user.is_contributor
            ):
                user.is_contributor = True
            if command.first_name and not user.first_name:
                user.first_name = command.first_name.strip()
            if command.last_name and not user.last_name:
                user.last_name = command.last_name.strip()
            user.save()

            # Display name and photo (when supplied during invite) were
            # already written to the CustomUser + UserProfile by the
            # create-invite use case — they live on the user model where
            # they belong. We just ensure the profile parks the active
            # workspace context so the first dashboard render lands on
            # the right org.
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.active_workspace_id = invitation.workspace_id
            if invitation.team_id:
                profile.active_team_id = invitation.team_id
            profile.save()

            # Write the persona + role membership row. Double-write the
            # new workspace_role FK so RBAC readers can migrate to the
            # FK once Phase 2 lands. System-role lookup is a single
            # query scoped to the seeded templates.
            #
            # Critical: if the user already has an active membership in
            # this workspace, we MUST NOT clobber their persona/role/
            # workspace_role with the invitation's values. Doing so
            # silently demotes existing owners and admins (this is what
            # broke when Henry self-invited as a contributor — his
            # OWNER row got rewritten to MEMBER). The invitation in
            # that case is a no-op for role/persona; we just mark it
            # accepted so the token is consumed. (The membership lookup
            # itself happened up-front so the user-flag write above
            # could decide whether to touch ``is_contributor``.)
            from infrastructure.persistence.workspaces.models import WorkspaceRole

            if preserving_existing_membership:
                # Preserve role/persona/workspace_role/invited_by; only
                # refresh accepted_at so audit trails stay accurate.
                existing_membership.accepted_at = now
                existing_membership.save(update_fields=["accepted_at"])
            else:
                system_role = (
                    WorkspaceRole.objects
                    .filter(
                        workspace__isnull=True,
                        is_system=True,
                        slug=invitation.role,
                    )
                    .first()
                )
                WorkspaceMembership.objects.update_or_create(
                    workspace_id=invitation.workspace_id,
                    user_id=user.id,
                    defaults={
                        "persona": invitation.persona,
                        "role": invitation.role,
                        "workspace_role": system_role,
                        "status": WorkspaceMembership.Status.ACTIVE,
                        "invited_by_id": invitation.invited_by_id,
                        "accepted_at": now,
                    },
                )

            # For team-attached personas, also enroll in the team. We use
            # the existing repository helper so we don't reinvent that
            # logic here.
            if invitation.team_id:
                try:
                    from components.team.infrastructure.repositories.team_membership_repository import (
                        TeamMembershipRepository,
                    )
                    repo = TeamMembershipRepository()
                    repo.enroll_user_in_team(
                        user,
                        invitation.workspace,
                        invitation.team,
                        update_active_context=True,
                    )
                except Exception:
                    # Team enrollment failure shouldn't block accept; the
                    # WorkspaceMembership row is already written.
                    pass

            # Enroll the user into any permission groups the inviter
            # selected. WorkspaceGroupMembership has a unique_together
            # constraint so we use get_or_create to stay idempotent.
            permission_group_ids = list(
                getattr(invitation, "permission_group_ids", []) or []
            )
            if permission_group_ids:
                from infrastructure.persistence.workspaces.models import (
                    WorkspaceGroup,
                    WorkspaceGroupMembership,
                )
                groups = WorkspaceGroup.objects.filter(
                    workspace_id=invitation.workspace_id,
                    id__in=permission_group_ids,
                )
                for group in groups:
                    WorkspaceGroupMembership.objects.get_or_create(
                        group=group,
                        user=user,
                        defaults={"added_by_id": invitation.invited_by_id},
                    )

            # Issue JWT tokens INSIDE the atomic block so any failure here
            # rolls back the user/membership/invitation writes together.
            # Previously the invitation was marked ACCEPTED before token
            # issuance, and a crash on the (broken) legacy CustomUser
            # .tokens() helper left the DB in a half-committed state where
            # the invite couldn't be retried. We use simplejwt directly
            # because the legacy helper imports a module that doesn't
            # exist in this codebase.
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)

            invitation.status = Invitation.ACCEPTED
            invitation.accepted_at = now
            invitation.save(update_fields=["status", "accepted_at"])

        return AcceptWorkspaceInviteResult(
            payload={
                "user_id": str(user.id),
                "email": user.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "workspace_id": str(invitation.workspace_id),
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "is_existing_user": is_existing_user,
            },
            status_code=200,
        )

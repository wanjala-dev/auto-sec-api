"""Use case for creating a workspace invitation (any persona).

This is the single source of truth for "admin invites someone to a workspace"
across every persona. It is parameterised by ``persona`` and routes to the
right enrollment branch on accept:

- team-attached personas (contributor, volunteer) → require ``team_id`` and
  the accept use case will enroll the user in the team
- team-detached personas (sponsor, auditor, board_member) → ``team_id`` is
  ignored; the accept use case only writes the WorkspaceMembership row

Magic-link tokens are 32-byte cryptographic secrets, hex-encoded, with a
24h expiry. The acceptance flow validates token + expiry, lets the user set
a password, then activates the membership.

Permission: only workspace owner or admin (RBAC role check). Persona is
not consulted for permissions — see ADR 0002.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from components.shared_kernel.application.transactional import atomic


def _utc_now():
    """Stdlib replacement for ``django.utils.timezone.now`` (UTC, tz-aware)."""
    return datetime.now(UTC)


def _ensure_aware(value):
    """Stdlib replacement for ``django.utils.timezone.make_aware``."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_aware(value):
    """Stdlib replacement for ``django.utils.timezone.is_aware``."""
    return value.tzinfo is not None


TEAM_ATTACHED_PERSONAS = frozenset({"contributor", "volunteer"})
# Admin sits in the team-detached bucket because admins are workspace-
# scoped — they don't enroll into a single team. Adviser is the
# "guest on someone's personal workspace" tier (family member, accountant) —
# also team-detached because personal workspaces don't have teams to
# enroll into.
TEAM_DETACHED_PERSONAS = frozenset({"admin", "sponsor", "auditor", "board_member", "adviser"})
INVITABLE_PERSONAS = TEAM_ATTACHED_PERSONAS | TEAM_DETACHED_PERSONAS

# Reasonable RBAC defaults per persona — admin can override on the request.
DEFAULT_ROLE_BY_PERSONA = {
    "admin": "admin",
    "contributor": "member",
    "volunteer": "member",
    "sponsor": "viewer",
    "auditor": "viewer",
    "board_member": "viewer",
    "adviser": "viewer",
}


@dataclass(frozen=True)
class CreateWorkspaceInviteCommand:
    workspace_id: str
    email: str
    persona: str
    inviter_user_id: str | None
    inviter_is_staff: bool = False
    inviter_is_superuser: bool = False
    role: str | None = None  # override default; otherwise DEFAULT_ROLE_BY_PERSONA
    team_id: str | None = None  # only used for team-attached personas
    expires_in_hours: int = 24
    display_name: str | None = None
    photo_url: str | None = None
    permission_group_ids: list | None = None


@dataclass(frozen=True)
class CreateWorkspaceInviteResult:
    payload: dict | None = None
    error: str | None = None
    status_code: int = 201


@dataclass
class CreateWorkspaceInviteUseCase:
    """Create a magic-link invitation row for a workspace persona."""

    def execute(self, command: CreateWorkspaceInviteCommand) -> CreateWorkspaceInviteResult:
        # Local imports keep the use case Django-free at module load time.
        from infrastructure.persistence.team.models import Invitation, Team
        from infrastructure.persistence.users.models import CustomUser, UserProfile
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceGroup,
            WorkspaceMembership,
        )

        # Validate persona.
        if command.persona not in INVITABLE_PERSONAS:
            return CreateWorkspaceInviteResult(
                error=f"Persona '{command.persona}' is not invitable.",
                status_code=400,
            )

        # Validate email.
        email = (command.email or "").strip().lower()
        if not email or "@" not in email:
            return CreateWorkspaceInviteResult(
                error="A valid email address is required.",
                status_code=400,
            )

        # Block self-invite. Accepting a self-invite previously rewrote
        # the inviter's own membership row to whatever persona/role the
        # invitation carried — silently demoting workspace owners to
        # contributors. Reject up front so it never reaches accept.
        if command.inviter_user_id:
            inviter = CustomUser.objects.filter(id=command.inviter_user_id).first()
            inviter_email = (getattr(inviter, "email", "") or "").strip().lower()
            if inviter_email and inviter_email == email:
                return CreateWorkspaceInviteResult(
                    error="You can't invite yourself to a workspace.",
                    status_code=400,
                )

        # Validate workspace.
        workspace = Workspace.objects.filter(id=command.workspace_id).first()
        if workspace is None:
            return CreateWorkspaceInviteResult(
                error="Workspace not found.",
                status_code=404,
            )

        # Permission check — RBAC role only. Owner or admin (or staff/superuser).
        is_authorized = command.inviter_is_staff or command.inviter_is_superuser
        if not is_authorized:
            if str(workspace.workspace_owner_id) == str(command.inviter_user_id):
                is_authorized = True
            else:
                is_authorized = WorkspaceMembership.objects.filter(
                    workspace_id=workspace.id,
                    user_id=command.inviter_user_id,
                    status=WorkspaceMembership.Status.ACTIVE,
                    role__in=(
                        WorkspaceMembership.Role.OWNER,
                        WorkspaceMembership.Role.ADMIN,
                    ),
                ).exists()
        if not is_authorized:
            return CreateWorkspaceInviteResult(
                error="Only workspace owners or admins can invite people.",
                status_code=403,
            )

        # The recipient should land on the experience matching the
        # access tier the inviter granted. When the inviter granted
        # admin/owner access (role in {"admin", "owner"}), the persona
        # must be "admin" — otherwise the recipient sees the
        # contributor sidebar despite having full permissions, which
        # silently breaks the "you have full access" promise of the
        # invite UX. For every other (role, persona) pair the frontend
        # is the source of truth; the use case stores them as-is.
        # Resolved up-front so downstream checks (team requirement,
        # role default, etc.) all see the corrected persona —
        # otherwise an "admin role + contributor persona" payload
        # trips the team-required validation below.
        role = command.role or DEFAULT_ROLE_BY_PERSONA[command.persona]
        persona = command.persona
        if role in ("admin", "owner"):
            persona = "admin"

        # Resolve team for team-attached personas. Uses the coerced
        # persona so admin-coerced invites skip the team requirement.
        team = None
        if persona in TEAM_ATTACHED_PERSONAS:
            if not command.team_id:
                return CreateWorkspaceInviteResult(
                    error=f"team_id is required for persona '{persona}'.",
                    status_code=400,
                )
            team = Team.objects.filter(id=command.team_id, workspace=workspace).first()
            if team is None:
                return CreateWorkspaceInviteResult(
                    error="Team not found in this workspace.",
                    status_code=404,
                )

        token = secrets.token_hex(32)
        # django.utils.timezone.now respects USE_TZ so the value we
        # persist matches whatever shape Django expects on read-back.
        expires_at = _utc_now() + timedelta(hours=max(command.expires_in_hours, 1))

        # Optional inviter-supplied profile data. We write these straight
        # to the CustomUser + UserProfile (where they belong) rather than
        # duplicating them on the Invitation row. The user record acts as
        # the canonical home for display name + photo; the invitation just
        # carries the magic-link token + workspace/persona/role context.
        display_name = (command.display_name or "").strip()
        photo_url = (command.photo_url or "").strip()

        # Optional permission groups to enroll the invitee into on accept.
        # Validate they belong to the target workspace before parking them
        # on the invitation row — otherwise the inviter could attach groups
        # from another workspace they happen to know the IDs of.
        validated_group_ids = []
        if command.permission_group_ids:
            valid_ids = set(
                str(gid)
                for gid in WorkspaceGroup.objects.filter(
                    workspace_id=workspace.id,
                    id__in=[str(gid) for gid in command.permission_group_ids],
                ).values_list("id", flat=True)
            )
            validated_group_ids = [str(gid) for gid in command.permission_group_ids if str(gid) in valid_ids]

        with atomic():
            # Get-or-create a pending CustomUser for this email so the
            # display name and photo land on the user record immediately.
            # If the user already exists we never overwrite their existing
            # name/photo — only fill blanks.
            #
            # ``is_contributor`` is only seeded True when the invitation
            # actually carries the contributor persona. Previously this
            # was hard-coded True, which silently flagged every admin /
            # sponsor / auditor invite as a contributor and put them on
            # the contributor sidebar after accept. The flag now means
            # what it says: "this user has a contributor membership
            # somewhere."
            user, user_created = CustomUser.objects.get_or_create(
                email=email,
                defaults={
                    "username": email,
                    "is_active": True,
                    "is_verified": False,
                    "is_onboard_complete": True,
                    "is_contributor": persona == "contributor",
                },
            )
            # Brand-new placeholders must have an unusable password so
            # ``has_usable_password()`` is a reliable signal for "this
            # person already has an account they can log into". Django's
            # default empty-string password counts as usable, which
            # would otherwise misclassify every fresh invitee as an
            # established user.
            if user_created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            # An "established" user is one that already has a usable
            # password set — i.e. they signed up the normal way (or
            # accepted a prior invite and chose a password). A user we
            # just created, or one created by an earlier never-accepted
            # invite, has an unusable password and counts as new. This
            # signal drives the email template branch ("Accept invite"
            # vs "Set password & sign in") and the in-app notification.
            is_existing_user = (not user_created) and user.has_usable_password()
            user_dirty_fields = []
            if display_name:
                pieces = display_name.split(maxsplit=1)
                first = pieces[0]
                last = pieces[1] if len(pieces) > 1 else ""
                if not user.first_name:
                    user.first_name = first
                    user_dirty_fields.append("first_name")
                if last and not user.last_name:
                    user.last_name = last
                    user_dirty_fields.append("last_name")
            if user_dirty_fields:
                user.save(update_fields=user_dirty_fields)

            if photo_url:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                if not profile.photo_url:
                    profile.photo_url = photo_url[:120]
                    profile.save(update_fields=["photo_url"])

            invitation = Invitation.objects.create(
                workspace=workspace,
                team=team,
                email=email,
                code=token[:20],  # legacy short code mirrors the token prefix
                token=token,
                persona=persona,
                role=role,
                invited_by_id=command.inviter_user_id,
                expires_at=expires_at,
                status=Invitation.INVITED,
                permission_group_ids=validated_group_ids,
            )

        # Send the magic-link email. Best-effort — if SMTP is down or the
        # template render fails we still return the token in the payload
        # so admins can copy a link manually from the invitations tab.
        inviter_user = None
        if command.inviter_user_id:
            inviter_user = CustomUser.objects.filter(id=command.inviter_user_id).first()
        try:
            from components.team.infrastructure.adapters.utilities import (
                send_persona_invitation,
            )

            send_persona_invitation(
                invitation,
                inviter_user=inviter_user,
                is_existing_user=is_existing_user,
            )
        except Exception:
            import logging

            logging.getLogger("invitations").exception(
                "persona invite email failed for %s",
                invitation.email,
            )

        # In-app notification for established users. New users haven't
        # got an account to land on yet; they only need the email. We
        # swallow notification failures because the email is the
        # primary channel — bell-icon ping is just a nicety.
        if is_existing_user and inviter_user is not None:
            try:
                from components.notifications.application.providers.notification_factory_provider import (
                    get_notification_factory_provider,
                )

                get_notification_factory_provider().dispatch(
                    actor=inviter_user,
                    workspace=workspace,
                    verb=f"invited you to join {workspace.workspace_name or 'a workspace'}",
                    notification_type="workspace_invitation",
                    recipients=[user],
                    target=invitation,
                    metadata={
                        "invitation_id": str(invitation.id),
                        "persona": invitation.persona,
                        "role": invitation.role,
                        "token": token,
                    },
                )
            except Exception:
                import logging

                logging.getLogger("invitations").exception(
                    "persona invite in-app notification failed for %s",
                    invitation.email,
                )

        return CreateWorkspaceInviteResult(
            payload={
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "expires_at": expires_at.isoformat(),
                "token": token,
                "is_existing_user": is_existing_user,
            },
            status_code=201,
        )

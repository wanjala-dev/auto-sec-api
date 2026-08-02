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

Ownership boundaries (architecture-manifesto Rule 2 / architecture-skill C2/C3):
the ``CustomUser``/``UserProfile`` write is owned by ``identity`` (via
``InviteUserProvisioningPort``); the workspace validation + authorization +
group-ownership reads are owned by ``workspace`` (via
``WorkspaceInviteContextPort``); the ``Invitation`` write is own-context (via
``InvitationStorePort``). This use case orchestrates them and holds no ORM.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from components.shared_kernel.application.transactional import atomic
from components.team.application.ports.invitation_store_port import InvitationStorePort
from components.team.application.ports.invite_notifier_port import InviteNotifierPort
from components.team.application.ports.invite_user_provisioning_port import (
    InviteUserProvisioningPort,
)
from components.team.application.ports.workspace_invite_context_port import (
    WorkspaceInviteContextPort,
)


def _utc_now():
    """Stdlib replacement for ``django.utils.timezone.now`` (UTC, tz-aware)."""
    return datetime.now(UTC)


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

    invitations: InvitationStorePort
    user_provisioning: InviteUserProvisioningPort
    invite_context: WorkspaceInviteContextPort
    notifier: InviteNotifierPort

    def execute(self, command: CreateWorkspaceInviteCommand) -> CreateWorkspaceInviteResult:
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
            inviter_email = self.invite_context.get_inviter_email(inviter_user_id=str(command.inviter_user_id))
            if inviter_email and inviter_email == email:
                return CreateWorkspaceInviteResult(
                    error="You can't invite yourself to a workspace.",
                    status_code=400,
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

        team_required = persona in TEAM_ATTACHED_PERSONAS

        # Validate the workspace, authorize the inviter, resolve the team (when
        # a team_id was supplied), and validate permission-group ownership — all
        # workspace-owned reads, delegated to the workspace context. The adapter
        # returns raw facts only; the ORDERING of the resulting checks lives HERE
        # and must match main exactly: workspace-404 → auth-403 → team_id-400 →
        # team-not-found-404. (Moving the team_id/400 gate before auth would let
        # an unauthorized caller — or one targeting a nonexistent workspace —
        # get 400 instead of 403/404, an auth-path behaviour change.)
        context = self.invite_context.resolve_invite_context(
            workspace_id=str(command.workspace_id),
            inviter_user_id=str(command.inviter_user_id) if command.inviter_user_id else None,
            inviter_is_staff=command.inviter_is_staff,
            inviter_is_superuser=command.inviter_is_superuser,
            persona=persona,
            team_required=team_required,
            team_id=str(command.team_id) if command.team_id else None,
            permission_group_ids=command.permission_group_ids,
        )
        if not context.workspace_found:
            return CreateWorkspaceInviteResult(
                error="Workspace not found.",
                status_code=404,
            )
        if not context.authorized:
            return CreateWorkspaceInviteResult(
                error="Only workspace owners or admins can invite people.",
                status_code=403,
            )
        if team_required and not command.team_id:
            return CreateWorkspaceInviteResult(
                error=f"team_id is required for persona '{persona}'.",
                status_code=400,
            )
        if team_required and not context.team_found:
            return CreateWorkspaceInviteResult(
                error="Team not found in this workspace.",
                status_code=404,
            )

        token = secrets.token_hex(32)
        expires_at = _utc_now() + timedelta(hours=max(command.expires_in_hours, 1))

        # Optional inviter-supplied profile data. Written to the CustomUser +
        # UserProfile by the identity provisioning surface (where they belong).
        display_name = (command.display_name or "").strip()
        photo_url = (command.photo_url or "").strip()

        validated_group_ids = list(context.validated_group_ids or [])

        with atomic():
            # Get-or-create the placeholder/established user (identity owns the
            # write). ``is_contributor`` seeds True only for contributor
            # invites so the flag stays honest.
            provisioned = self.user_provisioning.provision_for_create(
                email=email,
                seed_is_contributor=persona == "contributor",
                display_name=display_name,
                photo_url=photo_url,
            )
            is_existing_user = provisioned.established

            invitation = self.invitations.create(
                workspace_id=str(command.workspace_id),
                team_id=str(command.team_id) if (team_required and command.team_id) else None,
                email=email,
                code=token[:20],  # legacy short code mirrors the token prefix
                token=token,
                persona=persona,
                role=role,
                invited_by_id=str(command.inviter_user_id) if command.inviter_user_id else None,
                expires_at=expires_at,
                permission_group_ids=validated_group_ids,
            )

        # Send the magic-link email. Best-effort — if SMTP is down or the
        # template render fails we still return the token in the payload so
        # admins can copy a link manually from the invitations tab.
        self.notifier.send_invitation_email(
            invitation_id=invitation.id,
            inviter_user_id=str(command.inviter_user_id) if command.inviter_user_id else None,
            is_existing_user=is_existing_user,
        )

        # In-app notification for established users. New users haven't got an
        # account to land on yet; they only need the email.
        if is_existing_user:
            self.notifier.notify_existing_user(
                invitation_id=invitation.id,
                inviter_user_id=str(command.inviter_user_id) if command.inviter_user_id else None,
                recipient_user_id=provisioned.user_id,
                token=token,
            )

        return CreateWorkspaceInviteResult(
            payload={
                "invitation_id": invitation.id,
                "email": invitation.email,
                "persona": invitation.persona,
                "role": invitation.role,
                "expires_at": expires_at.isoformat(),
                "token": token,
                "is_existing_user": is_existing_user,
            },
            status_code=201,
        )

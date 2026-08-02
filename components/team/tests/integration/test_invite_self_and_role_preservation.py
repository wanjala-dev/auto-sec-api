"""Regression tests for the self-invite + role-preservation fixes.

Two bugs were causing workspace owners to lose their seat:

1. The invite create endpoint accepted ``email == inviter.email`` and
   issued a real magic-link. Accepting the link rewrote the inviter's
   own membership row to whatever persona/role the invitation carried,
   silently demoting them (Henry self-invited as ``contributor`` and
   his OWNER row was downgraded to MEMBER).
2. ``AcceptWorkspaceInviteUseCase`` used ``update_or_create(... defaults)``
   so any pre-existing active membership got clobbered with the
   invitation's persona/role/workspace_role — even when the existing
   role was strictly stronger.

These tests pin both fixes down. The first blocks the bug at create; the
second is belt-and-suspenders so an admin who somehow owns a token (e.g.
copy-paste from another invitation) can't be downgraded by accepting it.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.team.models import Invitation
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import (
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


def _create_user(email: str, *, password: str = "pass1234") -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email, password=password)
    UserProfile.objects.get_or_create(user=user)
    return user


def _ensure_owner_role() -> WorkspaceRole:
    role, _ = WorkspaceRole.objects.get_or_create(
        workspace=None,
        is_system=True,
        slug="owner",
        defaults={"name": "Owner", "description": "System owner role"},
    )
    return role


def _create_workspace(owner: CustomUser) -> Workspace:
    workspace = Workspace.objects.create(
        workspace_name="Self Invite Org",
        workspace_owner=owner,
        status="active",
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        persona="admin",
        role=WorkspaceMembership.Role.OWNER,
        workspace_role=_ensure_owner_role(),
        status=WorkspaceMembership.Status.ACTIVE,
    )
    return workspace


@pytest.mark.django_db
def test_inviter_cannot_invite_themselves():
    owner = _create_user("self@example.com")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": owner.email,
            "persona": "contributor",
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "yourself" in (response.data.get("error") or "").lower()
    assert not Invitation.objects.filter(email=owner.email).exists()


@pytest.mark.django_db
def test_self_invite_check_is_case_insensitive():
    owner = _create_user("mixed@example.com")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "MIXED@example.com",  # capitalised — must still block
            "persona": "contributor",
        },
        format="json",
    )

    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_accept_does_not_downgrade_existing_owner():
    """If somehow a token gets accepted by an existing owner, their role
    must stay OWNER. The use case should preserve the existing
    membership entirely and just consume the invitation."""
    owner = _create_user("ownerkeep@example.com")
    workspace = _create_workspace(owner)

    # Forge an invitation that, if accepted naively, would downgrade
    # the owner. We bypass the create endpoint (which now blocks self-
    # invite) so we exercise the accept-side guard directly.
    invitation = Invitation.objects.create(
        workspace=workspace,
        email=owner.email,
        token="b" * 64,
        code="OWNERKEEP",
        persona="contributor",
        role="member",
        invited_by=owner,
    )

    client = APIClient()
    response = client.post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": invitation.token},
        format="json",
    )
    assert response.status_code == 200, response.data

    membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
    assert membership.role == WorkspaceMembership.Role.OWNER
    assert membership.persona == "admin"
    assert membership.status == WorkspaceMembership.Status.ACTIVE
    invitation.refresh_from_db()
    assert invitation.status == Invitation.ACCEPTED


@pytest.mark.django_db
def test_accept_attaches_membership_for_brand_new_user():
    """Sanity check that the happy path still works: a user who is NOT
    yet a member gets the invitation's role/persona on accept."""
    owner = _create_user("inviter-fresh@example.com")
    workspace = _create_workspace(owner)
    invitee = _create_user("fresh-member@example.com")

    invitation = Invitation.objects.create(
        workspace=workspace,
        email=invitee.email,
        token="c" * 64,
        code="FRESH",
        persona="auditor",
        role="viewer",
        invited_by=owner,
    )

    client = APIClient()
    response = client.post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": invitation.token},
        format="json",
    )
    assert response.status_code == 200, response.data

    membership = WorkspaceMembership.objects.get(workspace=workspace, user=invitee)
    assert membership.role == "viewer"
    assert membership.persona == "auditor"
    assert membership.status == WorkspaceMembership.Status.ACTIVE


# ── create-flow validation ordering (auth path) ───────────────────────────
# The ordering is: workspace-404 → auth-403 → team_id-required-400 →
# team-not-found-404. The app-layer ORM burndown refactor split these checks
# across a workspace read-port; these tests pin that an unauthorized caller (or
# one targeting a nonexistent workspace) still gets 403/404 — NOT the 400 that a
# missing team_id would otherwise raise if that gate ran first.


@pytest.mark.django_db
def test_unauthorized_contributor_invite_without_team_is_403_not_400():
    """A non-member inviting a contributor with NO team_id must be rejected for
    authorization (403), not for the missing team_id (400). Auth outranks the
    team_id gate — moving the 400 first would leak that the workspace exists and
    change the auth-path status code."""
    owner = _create_user("owner-order@example.com")
    workspace = _create_workspace(owner)
    outsider = _create_user("outsider-order@example.com")

    client = APIClient()
    client.force_authenticate(user=outsider)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "invitee-order@example.com",
            "persona": "contributor",  # team-attached → would trip the 400 gate
            # deliberately NO team_id
        },
        format="json",
    )

    assert response.status_code == 403, response.data
    assert "owners or admins" in (response.data.get("error") or "").lower()
    assert not Invitation.objects.filter(email="invitee-order@example.com").exists()


@pytest.mark.django_db
def test_nonexistent_workspace_contributor_invite_without_team_is_404_not_400():
    """Targeting a workspace that doesn't exist must be 404 (workspace not
    found), not 400 (team_id required) — the workspace-existence check outranks
    the team_id gate."""
    owner = _create_user("owner-order2@example.com")
    _create_workspace(owner)  # a real workspace, but we target a bogus id

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": "00000000-0000-0000-0000-000000000000",
            "email": "invitee-order2@example.com",
            "persona": "contributor",  # team-attached → would trip the 400 gate
            # deliberately NO team_id
        },
        format="json",
    )

    assert response.status_code == 404, response.data
    assert "workspace not found" in (response.data.get("error") or "").lower()
    assert not Invitation.objects.filter(email="invitee-order2@example.com").exists()


# ── all-or-nothing rollback across the three contexts (security-critical) ──
# The accept flow writes THREE contexts (identity user, workspace membership,
# team invitation) under ONE atomic() at the team use-case boundary. A failure
# mid-provision MUST roll ALL of them back — a half-provisioned invite (a
# committed CustomUser with no membership, or an invitation flipped to ACCEPTED
# without the user) is a data-integrity + security bug. This test forces the
# membership write to raise mid-transaction and asserts nothing committed.


@pytest.mark.django_db
def test_accept_rolls_back_all_contexts_when_membership_write_fails(monkeypatch):
    owner = _create_user("owner-rollback@example.com")
    workspace = _create_workspace(owner)

    # Brand-new invitee (no CustomUser yet) so the accept flow must CREATE one;
    # if the transaction rolls back, that row must not survive.
    invitee_email = "brand-new-rollback@example.com"
    assert not CustomUser.objects.filter(email=invitee_email).exists()

    invitation = Invitation.objects.create(
        workspace=workspace,
        email=invitee_email,
        token="d" * 64,
        code="ROLLBACK",
        persona="auditor",
        role="viewer",
        invited_by=owner,
    )

    # Force the workspace membership write (the 2nd of the three context writes,
    # after the identity user provision) to blow up mid-transaction.
    from components.workspace.application.use_cases.write_invite_membership_use_case import (
        WriteInviteMembershipUseCase,
    )

    def _boom(self, *, command):
        raise RuntimeError("simulated membership write failure")

    monkeypatch.setattr(WriteInviteMembershipUseCase, "execute", _boom)

    # Let the view surface the failure as a 500 rather than re-raising into the
    # test, so we assert the OUTCOME (rollback) regardless of how the error
    # propagates through DRF's exception handler.
    client = APIClient(raise_request_exception=False)
    response = client.post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": invitation.token, "password": "brandnewpass123"},
        format="json",
    )
    assert response.status_code == 500, response.data

    # 1. identity: the CustomUser provisioned earlier in the same atomic() must
    #    have been rolled back — no orphaned account.
    assert not CustomUser.objects.filter(email=invitee_email).exists()
    # 2. workspace: no membership row for this workspace beyond the owner.
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user__email=invitee_email).exists()
    # 3. team: the invitation was NOT consumed — still INVITED, retriable.
    invitation.refresh_from_db()
    assert invitation.status == Invitation.INVITED
    assert invitation.accepted_at is None

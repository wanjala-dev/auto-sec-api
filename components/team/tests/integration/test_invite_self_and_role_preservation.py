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
    user = CustomUser.objects.create_user(
        email=email, username=email, password=password
    )
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

    membership = WorkspaceMembership.objects.get(
        workspace=workspace, user=owner
    )
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

    membership = WorkspaceMembership.objects.get(
        workspace=workspace, user=invitee
    )
    assert membership.role == "viewer"
    assert membership.persona == "auditor"
    assert membership.status == WorkspaceMembership.Status.ACTIVE

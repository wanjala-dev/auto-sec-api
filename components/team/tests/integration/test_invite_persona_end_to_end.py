"""End-to-end persona contract tests.

These tests sweep every invitable persona (admin, contributor, volunteer,
sponsor, auditor, board_member) through the full create → accept loop
and assert the recipient lands with the persona the inviter chose. They
also pin down the role → persona coercion rule (admin/owner roles
always force admin persona) and the user.is_contributor flag (only set
True when the invitation persona is "contributor", never on accept of
any other persona).

This file exists because the same regression class — invitee persona
silently mutated to "contributor" during invite/accept — bit us twice.
The test sweep makes that whole regression class noisy: any change that
breaks the persona contract for any persona will fail one of these.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.team.models import Invitation, Team
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


def _create_workspace(owner: CustomUser, name: str = "Persona Sweep Org") -> Workspace:
    workspace = Workspace.objects.create(
        workspace_name=name,
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


def _create_team(workspace: Workspace, owner: CustomUser, title: str = "Alpha") -> Team:
    return Team.objects.create(
        workspace=workspace,
        title=title,
        created_by=owner,
    )


# (persona sent, expects_team, expected_membership_persona, expected_is_contributor)
PERSONA_MATRIX = [
    ("admin", False, "admin", False),
    ("contributor", True, "contributor", True),
    ("volunteer", True, "volunteer", False),
    ("sponsor", False, "sponsor", False),
    ("auditor", False, "auditor", False),
    ("board_member", False, "board_member", False),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invite_persona,needs_team,expected_persona,expected_is_contributor",
    PERSONA_MATRIX,
)
def test_invite_accept_lands_with_correct_persona(
    invite_persona, needs_team, expected_persona, expected_is_contributor
):
    """For every invitable persona, the full create → accept loop
    leaves the recipient with the persona the inviter chose, and the
    global is_contributor flag reflects whether they were actually
    invited as a contributor."""
    owner = _create_user(f"owner-{invite_persona}@example.com")
    workspace = _create_workspace(owner, name=f"{invite_persona} Org")
    invitee_email = f"invitee-{invite_persona}@example.com"

    payload = {
        "workspace_id": str(workspace.id),
        "email": invitee_email,
        "persona": invite_persona,
    }
    if needs_team:
        team = _create_team(workspace, owner, title=f"{invite_persona}-team")
        payload["team_id"] = team.id

    client = APIClient()
    client.force_authenticate(user=owner)
    create_resp = client.post(
        reverse("membership:membership-persona-invite"),
        payload,
        format="json",
    )
    assert create_resp.status_code == 201, f"create failed for persona={invite_persona}: {create_resp.data}"

    invitation = Invitation.objects.get(email=invitee_email, workspace=workspace)
    assert invitation.persona == expected_persona

    placeholder = CustomUser.objects.get(email=invitee_email)
    assert placeholder.is_contributor is expected_is_contributor, (
        f"placeholder.is_contributor wrong for persona={invite_persona}"
    )

    accept_client = APIClient()
    accept_resp = accept_client.post(
        reverse("membership:membership-persona-invite-accept"),
        {
            "token": create_resp.data["token"],
            "password": "newpass123",
            "first_name": "Test",
            "last_name": "User",
        },
        format="json",
    )
    assert accept_resp.status_code == 200, f"accept failed for persona={invite_persona}: {accept_resp.data}"

    accepted_user = CustomUser.objects.get(email=invitee_email)
    assert accepted_user.is_contributor is expected_is_contributor, (
        f"post-accept is_contributor wrong for persona={invite_persona}"
    )

    membership = WorkspaceMembership.objects.get(workspace=workspace, user=accepted_user)
    assert membership.persona == expected_persona, f"membership.persona wrong for persona={invite_persona}"
    assert membership.status == WorkspaceMembership.Status.ACTIVE


# (selected_persona, role_override, expected_persona, expected_role)
ROLE_COERCION_MATRIX = [
    # Admin/owner roles MUST coerce persona → admin regardless of
    # what the inviter picked in step 1.
    ("contributor", "admin", "admin", "admin"),
    ("volunteer", "admin", "admin", "admin"),
    ("sponsor", "admin", "admin", "admin"),
    ("auditor", "admin", "admin", "admin"),
    ("board_member", "admin", "admin", "admin"),
    ("contributor", "owner", "admin", "owner"),
    ("sponsor", "owner", "admin", "owner"),
    # Non-elevated roles preserve the chosen persona.
    ("contributor", "member", "contributor", "member"),
    ("volunteer", "member", "volunteer", "member"),
    ("sponsor", "viewer", "sponsor", "viewer"),
    ("auditor", "viewer", "auditor", "viewer"),
    ("board_member", "viewer", "board_member", "viewer"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "sent_persona,sent_role,expected_persona,expected_role",
    ROLE_COERCION_MATRIX,
)
def test_role_coerces_persona_to_admin_for_elevated_roles_only(
    sent_persona, sent_role, expected_persona, expected_role
):
    """The use case's role-coercion rule pinned: admin/owner roles
    force persona='admin'; every other role keeps the chosen persona."""
    owner = _create_user(f"owner-{sent_persona}-{sent_role}@example.com")
    workspace = _create_workspace(owner, name=f"{sent_persona}-{sent_role} Org")
    invitee_email = f"invitee-{sent_persona}-{sent_role}@example.com"

    payload = {
        "workspace_id": str(workspace.id),
        "email": invitee_email,
        "persona": sent_persona,
        "role": sent_role,
    }
    if sent_persona in ("contributor", "volunteer") and (expected_persona == sent_persona):
        team = _create_team(workspace, owner, title=f"{sent_persona}-{sent_role}-team")
        payload["team_id"] = team.id

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        payload,
        format="json",
    )
    assert response.status_code == 201, f"create failed for {sent_persona}/{sent_role}: {response.data}"

    invitation = Invitation.objects.get(email=invitee_email, workspace=workspace)
    assert invitation.persona == expected_persona, (
        f"persona coercion broken for {sent_persona}/{sent_role}: "
        f"got {invitation.persona!r}, expected {expected_persona!r}"
    )
    assert invitation.role == expected_role


@pytest.mark.django_db
def test_existing_higher_role_member_invited_again_keeps_role_and_persona():
    """If someone is already an active OWNER on a workspace and an
    invite gets accepted on the same email (e.g. someone re-invites the
    owner without realising), neither persona, role, nor is_contributor
    flag should be touched — the membership preserve guard kicks in
    AND the is_contributor guard prevents the global flag from being
    flipped to True."""
    owner = _create_user("preserved-owner@example.com")
    workspace = _create_workspace(owner)

    # Forge a contributor invite that bypasses the self-invite block,
    # so we exercise accept-side preservation directly. (Self-invite
    # is blocked at create; we hand-write the row to test accept.)
    invitation = Invitation.objects.create(
        workspace=workspace,
        email=owner.email,
        token="d" * 64,
        code="PRESERVED",
        persona="contributor",
        role="member",
        invited_by=owner,
    )

    initial_is_contributor = owner.is_contributor

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

    owner.refresh_from_db()
    assert owner.is_contributor is initial_is_contributor

"""Tests for the admin-invite UX coupling.

Granting workspace admin access (role='admin') used to leave the
invitation's persona at its default ('contributor'), which silently put
the recipient on the contributor sidebar despite having admin
permissions. The fix:

1. The use case forces persona='admin' whenever role resolves to 'admin'
   (belt-and-suspenders behind the frontend already aligning the
   payload).
2. ``user.is_contributor`` is only seeded True when the invitation
   actually carries the contributor persona — admin / sponsor / auditor
   invites no longer flip the global flag.
3. Accepting a contributor invite still promotes ``is_contributor``
   forward (regression guard).
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


def _create_workspace(owner: CustomUser, name: str = "Admin Coupling Org") -> Workspace:
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


@pytest.mark.django_db
def test_admin_role_forces_admin_persona():
    """Even when frontend sends persona='contributor' alongside
    role='admin', the backend must coerce persona to 'admin' so the
    recipient lands on the admin sidebar."""
    owner = _create_user("admin-coercer-owner@example.com")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "admin-recipient@example.com",
            "persona": "contributor",  # frontend may have stale default
            "role": "admin",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    invitation = Invitation.objects.get(workspace=workspace, email="admin-recipient@example.com")
    assert invitation.persona == "admin"
    assert invitation.role == "admin"


@pytest.mark.django_db
def test_admin_invite_does_not_set_global_is_contributor_flag():
    owner = _create_user("admin-flag-owner@example.com")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "future-admin@example.com",
            "persona": "admin",
            "role": "admin",
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    placeholder = CustomUser.objects.get(email="future-admin@example.com")
    assert placeholder.is_contributor is False


@pytest.mark.django_db
def test_accepting_admin_invite_lands_with_admin_persona_and_role():
    owner = _create_user("admin-accept-owner@example.com")
    workspace = _create_workspace(owner)

    create_client = APIClient()
    create_client.force_authenticate(user=owner)
    create_resp = create_client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "admin-accepter@example.com",
            "persona": "admin",
            "role": "admin",
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.data
    token = create_resp.data["token"]

    accept_client = APIClient()
    accept_resp = accept_client.post(
        reverse("membership:membership-persona-invite-accept"),
        {
            "token": token,
            "password": "newpass123",
            "first_name": "Ada",
            "last_name": "Min",
        },
        format="json",
    )
    assert accept_resp.status_code == 200, accept_resp.data

    accepted_user = CustomUser.objects.get(email="admin-accepter@example.com")
    assert accepted_user.is_contributor is False

    membership = WorkspaceMembership.objects.get(workspace=workspace, user=accepted_user)
    assert membership.role == "admin"
    assert membership.persona == "admin"


@pytest.mark.django_db
def test_sponsor_invite_does_not_set_is_contributor():
    owner = _create_user("sponsor-owner@example.com")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "fresh-sponsor@example.com",
            "persona": "sponsor",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    placeholder = CustomUser.objects.get(email="fresh-sponsor@example.com")
    assert placeholder.is_contributor is False


@pytest.mark.django_db
def test_contributor_invite_still_sets_is_contributor():
    """Regression guard — the legitimate contributor invite path keeps
    its existing semantics."""
    from infrastructure.persistence.team.models import Team

    owner = _create_user("contrib-owner@example.com")
    workspace = _create_workspace(owner)

    team = Team.objects.create(
        workspace=workspace,
        title="Contribs",
        created_by=owner,
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "fresh-contrib@example.com",
            "persona": "contributor",
            "team_id": team.id,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    placeholder = CustomUser.objects.get(email="fresh-contrib@example.com")
    assert placeholder.is_contributor is True

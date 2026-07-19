"""Regression tests for the persona-invite manage endpoint (cancel + resend).

The route uses ``<int:invitation_id>`` because ``Invitation.id`` is a
BigAutoField — switching to ``<uuid:>`` here breaks every cancel/resend
call from the Directories invitations tab. These tests pin that down.
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
)


def _create_user(email: str) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=email,
        password="pass1234",
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_workspace(owner: CustomUser) -> Workspace:
    workspace = Workspace.objects.create(
        workspace_name="Manage Org",
        workspace_owner=owner,
        status="active",
    )
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=owner,
        persona="admin",
        role=WorkspaceMembership.Role.OWNER,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    return workspace


def _create_invitation(workspace: Workspace, owner: CustomUser) -> Invitation:
    return Invitation.objects.create(
        workspace=workspace,
        email="invitee@example.com",
        token="a" * 64,
        code="ABC1234567",
        persona="auditor",
        role="viewer",
        invited_by=owner,
    )


@pytest.mark.django_db
def test_cancel_invitation_marks_revoked():
    owner = _create_user("owner-cancel@example.com")
    workspace = _create_workspace(owner)
    invitation = _create_invitation(workspace, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse(
            "membership:membership-persona-invite-manage",
            kwargs={"invitation_id": invitation.id, "action": "cancel"},
        )
    )
    assert response.status_code == 200, response.data
    invitation.refresh_from_db()
    assert invitation.status == Invitation.REVOKED


@pytest.mark.django_db
def test_resend_invitation_mints_fresh_token():
    owner = _create_user("owner-resend@example.com")
    workspace = _create_workspace(owner)
    invitation = _create_invitation(workspace, owner)
    original_token = invitation.token

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse(
            "membership:membership-persona-invite-manage",
            kwargs={"invitation_id": invitation.id, "action": "resend"},
        )
    )
    assert response.status_code == 200, response.data
    invitation.refresh_from_db()
    assert invitation.token != original_token
    assert invitation.status == Invitation.INVITED
    assert response.data["token"] == invitation.token


@pytest.mark.django_db
def test_unknown_action_rejected():
    owner = _create_user("owner-bad-action@example.com")
    workspace = _create_workspace(owner)
    invitation = _create_invitation(workspace, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse(
            "membership:membership-persona-invite-manage",
            kwargs={"invitation_id": invitation.id, "action": "zap"},
        )
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_non_admin_cannot_manage_invitations():
    owner = _create_user("owner-rbac@example.com")
    stranger = _create_user("stranger-rbac@example.com")
    workspace = _create_workspace(owner)
    invitation = _create_invitation(workspace, owner)

    client = APIClient()
    client.force_authenticate(user=stranger)
    response = client.post(
        reverse(
            "membership:membership-persona-invite-manage",
            kwargs={"invitation_id": invitation.id, "action": "cancel"},
        )
    )
    assert response.status_code == 403

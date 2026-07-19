"""Integration tests for the existing-user persona invite flow.

Covers:
- Detecting an established user when creating an invite (drives the
  email template branch + the in-app notification).
- Accepting the invite without a password when the user already has one.
- The info endpoint that the frontend uses to pick the right UI.

The classic (new-user) magic-link path is exercised in
test_invitation_notifications.py. These tests focus on what changed.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.team.models import Invitation
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import (
    Workspace,
    WorkspaceMembership,
)


def _create_user(email: str, *, password: str | None = None) -> CustomUser:
    user = CustomUser.objects.create_user(
        email=email,
        username=email,
        password=password,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_placeholder_user(email: str) -> CustomUser:
    """Mirror the row CreateWorkspaceInviteUseCase writes for a brand-new
    invitee: no usable password set."""
    user = CustomUser.objects.create(
        email=email,
        username=email,
        is_active=True,
        is_verified=False,
        is_onboard_complete=True,
        is_contributor=True,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    UserProfile.objects.get_or_create(user=user)
    return user


def _create_workspace(owner: CustomUser) -> Workspace:
    workspace = Workspace.objects.create(
        workspace_name="Existing User Org",
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


@pytest.mark.django_db
def test_invite_to_existing_user_uses_accept_branch_in_email():
    owner = _create_user("owner-exist@example.com", password="ownerpass1")
    invited = _create_user("invited-exist@example.com", password="invitedpass1")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": invited.email,
            "persona": "auditor",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["is_existing_user"] is True

    invite_messages = [msg for msg in mail.outbox if invited.email in msg.to]
    assert invite_messages
    html_body = invite_messages[-1].alternatives[0][0]
    # Existing-user email must NOT push them into a password setup flow.
    assert "Set Password &amp; Sign In" not in html_body
    assert "Set Password & Sign In" not in html_body
    assert "Accept Invite" in html_body
    assert "You already have an account" in html_body


@pytest.mark.django_db
def test_invite_to_new_user_keeps_password_setup_branch():
    owner = _create_user("owner-new@example.com", password="ownerpass1")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "fresh@example.com",
            "persona": "auditor",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["is_existing_user"] is False
    invite_messages = [msg for msg in mail.outbox if "fresh@example.com" in msg.to]
    assert invite_messages
    html_body = invite_messages[-1].alternatives[0][0]
    assert "Set Password" in html_body


@pytest.mark.django_db
def test_existing_user_invite_fires_in_app_notification(django_capture_on_commit_callbacks):
    owner = _create_user("owner-notify@example.com", password="ownerpass1")
    invited = _create_user("invited-notify@example.com", password="invitedpass1")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    # In-app invite ping flows through the dispatcher funnel (post-commit
    # enqueue) — flush on_commit callbacks so eager Celery runs.
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("membership:membership-persona-invite"),
            {
                "workspace_id": str(workspace.id),
                "email": invited.email,
                "persona": "auditor",
            },
            format="json",
        )
    assert response.status_code == 201, response.data

    assert Notification.objects.filter(
        recipient=invited,
        actor=owner,
        notification_type="workspace_invitation",
    ).exists()


@pytest.mark.django_db
def test_placeholder_user_is_not_treated_as_existing():
    """A user row with set_unusable_password (e.g. created by an earlier
    never-accepted invite) must NOT be treated as established."""
    owner = _create_user("owner-placeholder@example.com", password="ownerpass1")
    workspace = _create_workspace(owner)
    _create_placeholder_user("placeholder@example.com")

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "placeholder@example.com",
            "persona": "auditor",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["is_existing_user"] is False


@pytest.mark.django_db
def test_existing_user_can_accept_without_password():
    owner = _create_user("owner-accept@example.com", password="ownerpass1")
    invited = _create_user("invited-accept@example.com", password="oldpass123")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    create_resp = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": invited.email,
            "persona": "auditor",
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.data
    token = create_resp.data["token"]

    accept_client = APIClient()
    accept_resp = accept_client.post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": token},
        format="json",
    )
    assert accept_resp.status_code == 200, accept_resp.data
    assert accept_resp.data["is_existing_user"] is True
    assert accept_resp.data["access"]
    assert accept_resp.data["refresh"]

    invited.refresh_from_db()
    assert invited.check_password("oldpass123")  # password preserved
    assert WorkspaceMembership.objects.filter(
        workspace=workspace,
        user=invited,
        status=WorkspaceMembership.Status.ACTIVE,
    ).exists()
    assert Invitation.objects.get(token=token).status == Invitation.ACCEPTED


@pytest.mark.django_db
def test_new_user_accept_still_requires_password():
    owner = _create_user("owner-newaccept@example.com", password="ownerpass1")
    workspace = _create_workspace(owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    create_resp = client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": "newuser@example.com",
            "persona": "auditor",
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.data
    token = create_resp.data["token"]

    accept_client = APIClient()
    accept_resp = accept_client.post(
        reverse("membership:membership-persona-invite-accept"),
        {"token": token},
        format="json",
    )
    assert accept_resp.status_code == 400
    assert "Password is required" in accept_resp.data.get("error", "")


@pytest.mark.django_db
def test_persona_invite_info_endpoint_reports_existing_user():
    owner = _create_user("owner-info@example.com", password="ownerpass1")
    invited = _create_user("invited-info@example.com", password="invitedpass1")
    workspace = _create_workspace(owner)

    create_client = APIClient()
    create_client.force_authenticate(user=owner)
    create_resp = create_client.post(
        reverse("membership:membership-persona-invite"),
        {
            "workspace_id": str(workspace.id),
            "email": invited.email,
            "persona": "auditor",
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.data
    token = create_resp.data["token"]

    info_client = APIClient()
    info_resp = info_client.get(
        reverse("membership:membership-persona-invite-info"),
        {"token": token},
    )
    assert info_resp.status_code == 200
    assert info_resp.data["is_existing_user"] is True
    assert info_resp.data["email"] == invited.email
    assert info_resp.data["persona"] == "auditor"
    assert info_resp.data["workspace_name"] == workspace.workspace_name

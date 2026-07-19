"""Integration tests for the workspace-scoped user search endpoint.

The endpoint powers the InviteForm typeahead. It MUST scope results to
users who share at least one workspace with the requester so admins
can't probe email existence outside their own org.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

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


def _create_workspace(owner: CustomUser, name: str) -> Workspace:
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
        status=WorkspaceMembership.Status.ACTIVE,
    )
    return workspace


@pytest.mark.django_db
def test_returns_user_in_shared_workspace():
    actor = _create_user("actor@example.com")
    teammate = _create_user("teammate@example.com")
    workspace = _create_workspace(actor, "Shared Org")
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=teammate,
        persona="contributor",
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.get(
        reverse("membership:membership-user-search"),
        {"q": "teammate"},
    )
    assert response.status_code == 200
    emails = [r["email"] for r in response.data["results"]]
    assert "teammate@example.com" in emails


@pytest.mark.django_db
def test_excludes_users_outside_shared_workspaces():
    actor = _create_user("actor-isolated@example.com")
    stranger = _create_user("stranger@example.com")
    _create_workspace(actor, "Actor Org")
    other_owner = _create_user("other-owner@example.com")
    _create_workspace(other_owner, "Other Org")
    other_workspace = Workspace.objects.filter(
        workspace_owner=other_owner
    ).first()
    WorkspaceMembership.objects.create(
        workspace=other_workspace,
        user=stranger,
        persona="contributor",
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.get(
        reverse("membership:membership-user-search"),
        {"q": "stranger"},
    )
    assert response.status_code == 200
    emails = [r["email"] for r in response.data["results"]]
    assert "stranger@example.com" not in emails


@pytest.mark.django_db
def test_short_query_returns_empty():
    actor = _create_user("actor-short@example.com")
    _create_workspace(actor, "Org")
    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.get(
        reverse("membership:membership-user-search"),
        {"q": "a"},
    )
    assert response.status_code == 200
    assert response.data["results"] == []


@pytest.mark.django_db
def test_self_excluded_from_results():
    actor = _create_user("actor-self@example.com")
    _create_workspace(actor, "Org")

    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.get(
        reverse("membership:membership-user-search"),
        {"q": "actor-self"},
    )
    assert response.status_code == 200
    emails = [r["email"] for r in response.data["results"]]
    assert "actor-self@example.com" not in emails


@pytest.mark.django_db
def test_unauthenticated_request_rejected():
    client = APIClient()
    response = client.get(
        reverse("membership:membership-user-search"),
        {"q": "anyone"},
    )
    assert response.status_code in (401, 403)

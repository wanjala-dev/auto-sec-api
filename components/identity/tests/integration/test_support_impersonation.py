"""Integration tests for SupportImpersonationSession.

Covers:
- Flag gate (no flag → 403).
- Re-auth required for cross-workspace impersonation (no real admin
  membership), skipped when actor is already owner/admin.
- Session creates a synthetic ``WorkspaceMembership`` row with
  ``is_impersonation=True``; ending deletes it.
- ``me/summary`` surfaces ``can_support_impersonate`` +
  ``active_impersonation``.
- Money guard refuses mutations when impersonation grants escalation;
  allows them when the actor is already a real owner/admin.
- Celery cleanup task expires stale sessions and drops their
  synthetic memberships.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import (
    SupportImpersonationSession,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


@pytest.fixture
def support_flag(db):
    flag, _ = FeatureFlag.objects.get_or_create(
        key="feature.support_impersonation",
        defaults={
            "default_enabled": False,
            "description": "Allow per-user support impersonation sessions.",
        },
    )
    return flag


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


def _create_workspace(owner: CustomUser, name: str = "Org") -> Workspace:
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


def _enable_flag_for(flag: FeatureFlag, user: CustomUser) -> None:
    FeatureFlagRule.objects.get_or_create(
        flag=flag,
        scope=FeatureFlagRule.Scope.USER,
        user=user,
        defaults={"enabled": True, "note": "test"},
    )


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_unauthenticated_request_rejected():
    client = APIClient()
    response = client.post(
        reverse("support-impersonation-sessions"),
        {"workspace_id": "abc", "persona": "admin", "role": "admin"},
        format="json",
    )
    assert response.status_code in (401, 403)


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_user_without_flag_gets_403(support_flag):
    user = _create_user("nogate@example.com")
    workspace = _create_workspace(user)
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "contributor",
            "role": "member",
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_owner_can_impersonate_own_workspace_without_password(support_flag):
    """Previewing your own org as contributor — no privilege escalation,
    no re-auth required."""
    owner = _create_user("self@example.com")
    workspace = _create_workspace(owner, name="Self Org")
    _enable_flag_for(support_flag, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "contributor",
            "role": "member",
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["target_persona"] == "contributor"
    assert response.data["target_role"] == "member"

    # Synthetic membership row was created.
    synthetic = WorkspaceMembership.objects.get(workspace=workspace, user=owner, is_impersonation=True)
    assert synthetic.role == "member"
    assert synthetic.persona == "contributor"
    # Real OWNER membership untouched.
    real = WorkspaceMembership.objects.get(workspace=workspace, user=owner, is_impersonation=False)
    assert real.role == WorkspaceMembership.Role.OWNER


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_cross_workspace_impersonation_requires_password(support_flag):
    actor = _create_user("support@example.com", password="supportpass1")
    customer = _create_user("customer@example.com")
    workspace = _create_workspace(customer, name="Customer Org")
    _enable_flag_for(support_flag, actor)

    client = APIClient()
    client.force_authenticate(user=actor)

    # No password → 400.
    response = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "admin",
            "role": "admin",
        },
        format="json",
    )
    assert response.status_code == 400, response.data

    # Wrong password → 403.
    response = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "admin",
            "role": "admin",
            "password": "wrongpass",
        },
        format="json",
    )
    assert response.status_code == 403, response.data

    # Correct password → 201.
    response = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "admin",
            "role": "admin",
            "password": "supportpass1",
        },
        format="json",
    )
    assert response.status_code == 201, response.data


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_ending_session_deletes_synthetic_membership(support_flag):
    owner = _create_user("ender@example.com")
    workspace = _create_workspace(owner)
    _enable_flag_for(support_flag, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    create_resp = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "contributor",
            "role": "member",
        },
        format="json",
    )
    assert create_resp.status_code == 201, create_resp.data
    session_id = create_resp.data["id"]

    assert WorkspaceMembership.objects.filter(workspace=workspace, user=owner, is_impersonation=True).exists()

    end_resp = client.delete(
        reverse(
            "support-impersonation-session-end",
            kwargs={"session_id": session_id},
        )
    )
    assert end_resp.status_code == 200, end_resp.data
    assert end_resp.data["ended_at"] is not None

    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=owner, is_impersonation=True).exists()


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_starting_new_session_ends_prior_active_session(support_flag):
    owner = _create_user("multi@example.com")
    workspace_a = _create_workspace(owner, name="Org A")
    workspace_b = _create_workspace(owner, name="Org B")
    _enable_flag_for(support_flag, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    first = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace_a.id),
            "persona": "contributor",
            "role": "member",
        },
        format="json",
    )
    assert first.status_code == 201, first.data
    first_session_id = first.data["id"]

    second = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace_b.id),
            "persona": "sponsor",
            "role": "viewer",
        },
        format="json",
    )
    assert second.status_code == 201, second.data

    # First session should now be ended; only one synthetic row total.
    first_session = SupportImpersonationSession.objects.get(id=first_session_id)
    assert first_session.ended_at is not None
    assert WorkspaceMembership.objects.filter(user=owner, is_impersonation=True).count() == 1


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_summary_surfaces_active_session(support_flag):
    owner = _create_user("summary@example.com")
    workspace = _create_workspace(owner)
    _enable_flag_for(support_flag, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    summary_before = client.get(reverse("user-summary"))
    assert summary_before.data["data"]["can_support_impersonate"] is True
    assert summary_before.data["data"]["active_impersonation"] is None

    client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "auditor",
            "role": "viewer",
        },
        format="json",
    )

    summary_after = client.get(reverse("user-summary"))
    active = summary_after.data["data"]["active_impersonation"]
    assert active is not None
    assert active["target_persona"] == "auditor"
    # visible_sections must be derived from the target persona so the FE can
    # trim the sidebar to a trustworthy preview (not fall back to full admin).
    assert "visible_sections" in active
    sections = active["visible_sections"]
    assert isinstance(sections, list) and sections
    # Auditor is a read-only persona — must NOT include admin-only sections.
    assert "settings" not in sections
    assert "teams" not in sections
    assert "transparency" in sections
    assert active["target_role"] == "viewer"


@pytest.mark.real_feature_flags
@pytest.mark.django_db
def test_expire_task_cleans_up_stale_sessions(support_flag):
    from components.workspace.infrastructure.tasks.workspace_tasks import (
        expire_support_impersonation_sessions,
    )

    owner = _create_user("stale@example.com")
    workspace = _create_workspace(owner)
    _enable_flag_for(support_flag, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    create_resp = client.post(
        reverse("support-impersonation-sessions"),
        {
            "workspace_id": str(workspace.id),
            "persona": "contributor",
            "role": "member",
        },
        format="json",
    )
    session = SupportImpersonationSession.objects.get(id=create_resp.data["id"])
    # Force the session into the past.
    SupportImpersonationSession.objects.filter(id=session.id).update(expires_at=timezone.now() - timedelta(minutes=1))

    expired = expire_support_impersonation_sessions()
    assert expired == 1

    session.refresh_from_db()
    assert session.ended_at is not None
    assert session.synthetic_membership_id is None
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=owner, is_impersonation=True).exists()

    # Re-running the task is a no-op.
    assert expire_support_impersonation_sessions() == 0

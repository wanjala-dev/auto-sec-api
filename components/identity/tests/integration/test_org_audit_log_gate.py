"""Integration: the two gates on the org login-activity (audit log) surface.

1. ``feature.org_audit_log`` — Pro-tier product flag. Off (prod default
   for Free workspaces) → 403 on all three org routes AND the settings
   route; the personal ``/identity/me/*`` surfaces are unaffected.
2. Per-workspace ``audit_log_enabled`` admin toggle (stored in the
   shared WorkspacePreference JSON settings). Off → the three org
   routes 403 with machine code ``org_audit_log_disabled`` so the
   frontend can render a "turned off" state; the settings endpoints
   stay reachable (an admin must see enabled=false to flip it back);
   auth events keep recording; ``/me/*`` unaffected.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.notifications.userpreferences.models import (
    AUDIT_LOG_ENABLED_KEY,
    WorkspacePreference,
)
from infrastructure.persistence.users.models import AuthAuditEvent
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = pytest.mark.django_db

FLAG_KEY = "feature.org_audit_log"

LIST_URL = "workspace-login-activity"
DELETE_URL = "workspace-login-activity-delete"
SESSIONS_URL = "workspace-sessions"
SETTINGS_URL = "workspace-audit-log-settings"
SELF_ACTIVITY_URL = "my-login-activity"
SELF_SESSIONS_URL = "my-sessions"


def _set_flag(enabled: bool) -> None:
    flag, _ = FeatureFlag.objects.get_or_create(
        key=FLAG_KEY,
        defaults={"default_enabled": True, "description": "test-seeded"},
    )
    if enabled:
        FeatureFlagRule.objects.filter(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL).delete()
    else:
        FeatureFlagRule.objects.update_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.GLOBAL,
            defaults={"enabled": False, "note": "gate test"},
        )
    bump_feature_flags_version()


def _membership(workspace, user, *, role="member", status="active") -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role, status=status)


def _event(user, *, event_code="auth.login", success=True):
    return AuthAuditEvent.objects.create(
        user=user,
        email=user.email,
        event_code=event_code,
        success=success,
        ip_address="203.0.113.9",
        user_agent="pytest-browser/1.0",
    )


def _set_toggle(workspace, enabled: bool) -> None:
    preference, _ = WorkspacePreference.objects.get_or_create(workspace=workspace)
    preference.update_settings({AUDIT_LOG_ENABLED_KEY: enabled})


@pytest.fixture
def org(workspace_factory, user_factory):
    """Workspace with an admin (role=admin, ACTIVE) and a plain member."""
    workspace = workspace_factory()
    admin = user_factory(email="auditadmin@example.com")
    member = user_factory(email="auditmember@example.com")
    _membership(workspace, admin, role="admin")
    _membership(workspace, member, role="member")
    return workspace, admin, member


def _org_urls(workspace):
    return [
        ("get", reverse(LIST_URL, kwargs={"workspace_id": workspace.id})),
        ("get", reverse(SESSIONS_URL, kwargs={"workspace_id": workspace.id})),
        ("delete", reverse(DELETE_URL, kwargs={"workspace_id": workspace.id, "event_id": 12345})),
    ]


def _settings_url(workspace):
    return reverse(SETTINGS_URL, kwargs={"workspace_id": workspace.id})


@pytest.mark.real_feature_flags
class TestOrgAuditLogFeatureFlagGate:
    """Plan-tier flag off → the whole org audit surface is 403."""

    def test_flag_off_blocks_all_org_routes(self, api_client, org):
        workspace, admin, _member = org
        _set_flag(False)
        api_client.raise_request_exception = False
        api_client.force_authenticate(user=admin)

        for method, url in _org_urls(workspace):
            response = getattr(api_client, method)(url)
            assert response.status_code == 403, f"{method.upper()} {url} should 403 when {FLAG_KEY} is off"

        assert api_client.get(_settings_url(workspace)).status_code == 403
        assert api_client.patch(_settings_url(workspace), {"enabled": False}, format="json").status_code == 403

    def test_flag_off_leaves_personal_surfaces_untouched(self, api_client, org):
        _workspace, admin, _member = org
        _set_flag(False)
        _event(admin)
        api_client.force_authenticate(user=admin)

        assert api_client.get(reverse(SELF_ACTIVITY_URL)).status_code == 200
        assert api_client.get(reverse(SELF_SESSIONS_URL)).status_code == 200

    def test_flag_on_permits_org_routes(self, api_client, org):
        workspace, admin, _member = org
        _set_flag(True)
        _event(admin)
        api_client.force_authenticate(user=admin)

        assert api_client.get(reverse(LIST_URL, kwargs={"workspace_id": workspace.id})).status_code == 200
        assert api_client.get(reverse(SESSIONS_URL, kwargs={"workspace_id": workspace.id})).status_code == 200
        assert api_client.get(_settings_url(workspace)).status_code == 200


class TestOrgAuditLogToggle:
    """Per-workspace admin toggle (flag auto-enabled by conftest)."""

    def test_default_is_enabled(self, api_client, org):
        workspace, admin, _member = org
        api_client.force_authenticate(user=admin)

        response = api_client.get(_settings_url(workspace))

        assert response.status_code == 200
        assert response.data == {"enabled": True}

    def test_toggle_off_returns_403_with_machine_code_on_all_three_org_routes(self, api_client, org):
        workspace, admin, _member = org
        _set_toggle(workspace, False)
        api_client.raise_request_exception = False
        api_client.force_authenticate(user=admin)

        for method, url in _org_urls(workspace):
            response = getattr(api_client, method)(url)
            assert response.status_code == 403, f"{method.upper()} {url} should 403 when the toggle is off"
            assert response.data["code"] == "org_audit_log_disabled"
            assert "detail" in response.data

    def test_toggle_off_keeps_recording_and_personal_surfaces(self, api_client, org):
        """The toggle hides the org VIEW; collection + /me/* are untouched."""
        workspace, admin, _member = org
        _set_toggle(workspace, False)
        before = AuthAuditEvent.objects.count()
        _event(admin)  # events still record while the org view is off
        assert AuthAuditEvent.objects.count() == before + 1

        api_client.force_authenticate(user=admin)
        assert api_client.get(reverse(SELF_ACTIVITY_URL)).status_code == 200
        assert api_client.get(reverse(SELF_SESSIONS_URL)).status_code == 200

    def test_toggle_off_still_allows_settings_read_and_write(self, api_client, org):
        """An admin must be able to see enabled=false and flip it back on."""
        workspace, admin, _member = org
        _set_toggle(workspace, False)
        api_client.force_authenticate(user=admin)

        read = api_client.get(_settings_url(workspace))
        assert read.status_code == 200
        assert read.data == {"enabled": False}

        write = api_client.patch(_settings_url(workspace), {"enabled": True}, format="json")
        assert write.status_code == 200
        assert write.data == {"enabled": True}
        assert api_client.get(reverse(LIST_URL, kwargs={"workspace_id": workspace.id})).status_code == 200

    def test_admin_patch_flips_and_get_reflects(self, api_client, org):
        workspace, admin, _member = org
        api_client.force_authenticate(user=admin)

        response = api_client.patch(_settings_url(workspace), {"enabled": False}, format="json")
        assert response.status_code == 200
        assert response.data == {"enabled": False}
        assert api_client.get(_settings_url(workspace)).data == {"enabled": False}

        # PUT works the same as PATCH
        response = api_client.put(_settings_url(workspace), {"enabled": True}, format="json")
        assert response.status_code == 200
        assert api_client.get(_settings_url(workspace)).data == {"enabled": True}

    def test_patch_requires_enabled_field(self, api_client, org):
        workspace, admin, _member = org
        api_client.force_authenticate(user=admin)

        assert api_client.patch(_settings_url(workspace), {}, format="json").status_code == 400

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_non_admin_cannot_read_or_flip_toggle(self, api_client, org, user_factory, role):
        workspace, _admin, _member = org
        user = user_factory()
        _membership(workspace, user, role=role)
        api_client.force_authenticate(user=user)

        assert api_client.get(_settings_url(workspace)).status_code == 403
        assert api_client.patch(_settings_url(workspace), {"enabled": False}, format="json").status_code == 403

    def test_requires_authentication(self, api_client, org):
        workspace, _admin, _member = org
        assert api_client.get(_settings_url(workspace)).status_code == 401
        assert api_client.patch(_settings_url(workspace), {"enabled": False}, format="json").status_code == 401

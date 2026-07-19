"""Verify that each persona gets the correct role and visible_sections.

These tests ensure the backend → frontend contract works: when a user
logs in and calls /identity/me/summary/, their workspaces include
``role`` and ``visible_sections`` matching their persona.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from infrastructure.persistence.users.models import UserProfile

pytestmark = pytest.mark.django_db


def _set_active_workspace(user, workspace):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.active_workspace_id = workspace.id
    profile.save(update_fields=["active_workspace_id"])


def _get_summary(api_client, user):
    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("user-summary"))
    assert response.status_code == 200, response.data
    return response.data["data"]


def _find_workspace_in_payload(payload, workspace_id):
    ws_id = str(workspace_id)
    for ws in payload.get("workspaces", []):
        if ws["id"] == ws_id:
            return ws
    return None


class TestOwnerPersona:
    """Workspace owner gets full dashboard access."""

    def test_owner_role_and_sections(self, api_client, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        _set_active_workspace(owner, workspace)

        payload = _get_summary(api_client, owner)
        ws_data = _find_workspace_in_payload(payload, workspace.id)

        assert ws_data is not None, f"Workspace {workspace.id} not in summary"
        assert ws_data["role"] == "owner"
        sections = ws_data["visible_sections"]
        for expected in (
            "ai",
            "fundraising",
            "teams",
            "finance",
            "projects",
            "settings",
            "sponsorship",
            "campaigns",
            "grants",
        ):
            assert expected in sections, f"Owner missing section: {expected}"


class TestAdminPersona:
    """Admin team member gets full dashboard access (same as owner).

    Per ADR 0002 the UX-tier role is resolved from ``WorkspaceMembership.role``
    / ``.persona`` — NOT from "did this user create a team?" (that pre-ADR
    heuristic was removed; see ``workspace_role_policy`` docstring). An admin
    is therefore granted via an ADMIN-role membership row.
    """

    def test_admin_role_via_team_creator(self, api_client, user_factory, workspace_factory, team_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        admin = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, created_by=admin, members=[admin])
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=admin,
            role=WorkspaceMembership.Role.ADMIN,
            persona=WorkspaceMembership.Persona.ADMIN,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        _set_active_workspace(admin, workspace)

        payload = _get_summary(api_client, admin)
        ws_data = _find_workspace_in_payload(payload, workspace.id)

        assert ws_data is not None
        assert ws_data["role"] == "admin"
        sections = ws_data["visible_sections"]
        assert "ai" in sections
        assert "fundraising" in sections
        assert "settings" in sections
        assert "grants" in sections


class TestContributorPersona:
    """Regular team member (not creator) gets limited sections.

    Per ADR 0002 the contributor UX tier comes from a MEMBER-role /
    CONTRIBUTOR-persona ``WorkspaceMembership`` row — team membership alone
    no longer drives role resolution (see ``workspace_role_policy`` docstring).
    """

    def test_contributor_role(self, api_client, user_factory, workspace_factory, team_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        owner = user_factory()
        contributor = user_factory()
        workspace = workspace_factory(owner=owner)
        team_factory(workspace=workspace, created_by=owner, members=[owner, contributor])
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=contributor,
            role=WorkspaceMembership.Role.MEMBER,
            persona=WorkspaceMembership.Persona.CONTRIBUTOR,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        _set_active_workspace(contributor, workspace)

        payload = _get_summary(api_client, contributor)
        ws_data = _find_workspace_in_payload(payload, workspace.id)

        assert ws_data is not None
        assert ws_data["role"] == "contributor"
        sections = ws_data["visible_sections"]
        assert "projects" in sections
        assert "teams" in sections
        # Contributors should NOT see admin-level sections
        assert "campaigns" not in sections
        assert "sponsorship" not in sections


class TestSponsorPersona:
    """Follower (not team member, not owner) gets sponsor sections."""

    def test_sponsor_role_as_follower(self, api_client, user_factory, workspace_factory):
        owner = user_factory()
        sponsor = user_factory()
        workspace = workspace_factory(owner=owner)
        workspace.followers.add(sponsor)
        _set_active_workspace(sponsor, workspace)

        payload = _get_summary(api_client, sponsor)
        ws_data = _find_workspace_in_payload(payload, workspace.id)

        assert ws_data is not None
        assert ws_data["role"] == "sponsor"
        sections = ws_data["visible_sections"]
        assert "sponsorship" in sections
        assert "donations" in sections
        assert "transparency" in sections
        # Read-only access to grants for transparency
        assert "grants" in sections
        # Sponsors should NOT see internal sections
        assert "ai" not in sections
        assert "teams" not in sections
        assert "fundraising" not in sections


class TestPersonalPersona:
    """Personal workspace owner gets personal sections."""

    def test_personal_role(self, api_client, user_factory, workspace_factory):
        user = user_factory()

        from infrastructure.persistence.workspaces.models import Workspace

        personal_ws = Workspace.objects.create(
            workspace_name=f"{user.first_name}'s Space",
            workspace_owner=user,
            workspace_type="personal",
            status="active",
            privacy="private",
        )
        _set_active_workspace(user, personal_ws)

        payload = _get_summary(api_client, user)
        ws_data = _find_workspace_in_payload(payload, personal_ws.id)

        assert ws_data is not None
        assert ws_data["role"] == "personal"
        sections = ws_data["visible_sections"]
        assert "ai" in sections
        assert "finance" in sections
        assert "projects" in sections
        assert "settings" in sections
        # Personal users should NOT see org sections
        assert "fundraising" not in sections
        assert "sponsorship" not in sections
        assert "campaigns" not in sections
        assert "grants" not in sections


class TestPersonalSpaceFlagGate:
    """me/summary hides a personal workspace unless feature.personal_space is on.

    Marked real_feature_flags to bypass the autouse all-flags-on fixture and
    exercise the real cascade — same pattern as the support-impersonation and
    sectors_multi gate tests. This locks the "deployed but visible only to
    flagged users" contract: a personal workspace owned by the user is dropped
    from the entire summary when the flag is off.
    """

    pytestmark = pytest.mark.real_feature_flags

    @staticmethod
    def _set_personal_space(*, enabled: bool):
        from components.shared_platform.infrastructure.services.feature_flags import (
            bump_feature_flags_version,
        )
        from infrastructure.persistence.core.models import (
            FeatureFlag,
            FeatureFlagRule,
        )

        flag, _ = FeatureFlag.objects.get_or_create(
            key="feature.personal_space",
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

    def _make_personal_ws(self, user):
        from infrastructure.persistence.workspaces.models import Workspace

        ws = Workspace.objects.create(
            workspace_name=f"{user.first_name}'s Space",
            workspace_owner=user,
            workspace_type="personal",
            status="active",
            privacy="private",
        )
        _set_active_workspace(user, ws)
        return ws

    def test_personal_workspace_hidden_when_flag_off(self, api_client, user_factory):
        self._set_personal_space(enabled=False)
        user = user_factory()
        personal_ws = self._make_personal_ws(user)

        payload = _get_summary(api_client, user)

        assert payload.get("private_workspace") is None
        assert _find_workspace_in_payload(payload, personal_ws.id) is None

    def test_personal_workspace_surfaced_when_flag_on(self, api_client, user_factory):
        self._set_personal_space(enabled=True)
        user = user_factory()
        personal_ws = self._make_personal_ws(user)

        payload = _get_summary(api_client, user)

        assert payload.get("private_workspace") is not None
        assert payload["private_workspace"]["id"] == str(personal_ws.id)
        assert _find_workspace_in_payload(payload, personal_ws.id) is not None

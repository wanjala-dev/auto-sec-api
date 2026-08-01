"""Integration tests for the owner-gated sample-data-mode toggle (ADR 0011 Phase 1)."""

from __future__ import annotations

import pytest

from components.shared_platform.infrastructure.services.feature_flags import is_feature_enabled

_FLAG = "feature.sample_data_mode"


def _mode_url(ws_id):
    return f"/findings/workspaces/{ws_id}/sample-data/mode/"


def _sample_findings_exist(ws_id) -> bool:
    from infrastructure.persistence.findings.models import Finding

    return Finding.objects.filter(workspace_id=ws_id, source__startswith="sample.").exists()


@pytest.mark.django_db
class TestSampleDataModeToggle:
    def test_owner_enable_seeds_and_sets_flag(self, api_client, workspace_factory):
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        resp = api_client.post(_mode_url(ws.id), {"enabled": True}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["enabled"] is True
        # The coordinator returns an aggregate keyed by context (ADR 0011 Phase 2).
        assert resp.data["data"]["seeded"]["findings"]["seeded"] > 0
        assert is_feature_enabled(_FLAG, workspace_id=str(ws.id)) is True
        assert _sample_findings_exist(ws.id)

    def test_owner_disable_clears_and_unsets_flag(self, api_client, workspace_factory):
        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        api_client.post(_mode_url(ws.id), {"enabled": True}, format="json")
        resp = api_client.post(_mode_url(ws.id), {"enabled": False}, format="json")
        assert resp.status_code == 200
        assert resp.data["enabled"] is False
        # Assert the workspace rule state directly (the eval path is cache-invalidated by
        # bump_feature_flags_version in prod/Redis; the enable test covers the eval path).
        from infrastructure.persistence.core.models import FeatureFlagRule

        rule = FeatureFlagRule.objects.get(flag__key=_FLAG, workspace_id=ws.id)
        assert rule.enabled is False
        assert not _sample_findings_exist(ws.id)

    def test_non_owner_is_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(user_factory())  # a different, non-owner user
        resp = api_client.post(_mode_url(ws.id), {"enabled": True}, format="json")
        assert resp.status_code == 403
        assert not _sample_findings_exist(ws.id)

    def test_sample_findings_do_not_satisfy_first_scan(self, api_client, workspace_factory):
        # ADR 0011: demo mode must not falsely advance the live setup funnel.
        from components.workspace.infrastructure.repositories.workspace_setup_query_repository import (
            OrmWorkspaceSetupQueryRepository,
        )

        ws = workspace_factory()
        api_client.force_authenticate(ws.workspace_owner)
        api_client.post(_mode_url(ws.id), {"enabled": True}, format="json")
        assert _sample_findings_exist(ws.id)
        assert OrmWorkspaceSetupQueryRepository._has_first_scan(ws) is False

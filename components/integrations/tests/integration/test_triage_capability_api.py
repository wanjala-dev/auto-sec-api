"""Integration tests for the owner-gated triage-capability toggle API (ADR 0010).

``GET/PATCH /integrations/workspaces/<ws>/triage-capabilities/`` — the FE toggle's
backend. Owner can read + enable + disable; a non-owner member is 403; enabling on
a fresh workspace provisions the triage_agent row and flips
``config.capabilities.open_draft_pr``.
"""

from __future__ import annotations

import pytest


def _url(workspace_id):
    return f"/integrations/workspaces/{workspace_id}/triage-capabilities/"


def _triage_rows(workspace):
    from infrastructure.persistence.ai.agents.models import Agent

    return Agent.objects.filter(workspace=workspace, agent_type="triage_agent")


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


@pytest.mark.django_db
class TestTriageCapabilityApi:
    def test_get_reports_false_by_default(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.get(_url(ws.id))
        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["capabilities"] == {"open_draft_pr": False}
        assert resp.data["data"]["agent_type"] == "triage_agent"

    def test_owner_can_enable_then_disable(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)

        enabled = api_client.patch(_url(ws.id), {"enabled": True}, format="json")
        assert enabled.status_code == 200, enabled.data
        assert enabled.data["data"]["capabilities"]["open_draft_pr"] is True
        row = _triage_rows(ws).get()
        assert row.config["capabilities"]["open_draft_pr"] is True

        disabled = api_client.patch(_url(ws.id), {"enabled": False}, format="json")
        assert disabled.status_code == 200, disabled.data
        assert disabled.data["data"]["capabilities"]["open_draft_pr"] is False
        assert _triage_rows(ws).count() == 1  # idempotent — no duplicate row

    def test_enable_explicit_capability_key(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.patch(_url(ws.id), {"capability": "open_draft_pr", "enabled": True}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["capabilities"]["open_draft_pr"] is True

    def test_unknown_capability_is_400(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.patch(_url(ws.id), {"capability": "rm_rf", "enabled": True}, format="json")
        assert resp.status_code == 400
        assert not _triage_rows(ws).exists()

    def test_non_owner_member_is_forbidden(self, api_client, owner_ws, user_factory):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        ws, _ = owner_ws
        member = user_factory()
        WorkspaceMembership.objects.create(workspace=ws, user=member, status=WorkspaceMembership.Status.ACTIVE)
        api_client.force_authenticate(member)

        assert api_client.get(_url(ws.id)).status_code == 403
        assert api_client.patch(_url(ws.id), {"enabled": True}, format="json").status_code == 403
        assert not _triage_rows(ws).exists()

    def test_other_workspace_owner_is_forbidden(self, api_client, workspace_factory):
        """IDOR guard: Bob, a legitimate owner of workspace B, must NOT be able to
        read or flip workspace A's triage capability. Owner-ness is per-workspace —
        this is the exact failure mode a repo-write-granting endpoint must never
        regress."""
        ws_a = workspace_factory()  # owner Alice
        ws_b = workspace_factory()  # owner Bob
        bob = ws_b.workspace_owner
        api_client.force_authenticate(bob)

        assert api_client.get(_url(ws_a.id)).status_code == 403
        assert api_client.patch(_url(ws_a.id), {"enabled": True}, format="json").status_code == 403
        # And no side-effect: Bob's denied PATCH provisioned nothing for A.
        assert not _triage_rows(ws_a).exists()

    def test_anonymous_is_unauthorized(self, api_client, owner_ws):
        ws, _ = owner_ws
        assert api_client.get(_url(ws.id)).status_code in (401, 403)

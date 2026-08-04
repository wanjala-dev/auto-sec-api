"""Write API over the Finding SSOT — POST /api/v1/findings/workspaces/<ws>/<id>/status/.

Pins the operator action row behind the HUD finding-detail callout: membership-gated,
workspace-scoped, resolve/suppress/reopen — a lifecycle transition, never a hard delete.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _url(ws, finding):
    return f"/api/v1/findings/workspaces/{ws.id}/{finding.id}/status/"


def _member(ws, user_factory):
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    return member


def _finding(ws, *, status="open", fingerprint="fp-1"):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.trivy",
        fingerprint=fingerprint,
        asset_urn=f"arn:aws:ec2:{ws.id}::i-1",
        severity="high",
        status=status,
        title="CVE-2024-1234 in libfoo",
        first_seen_at=now,
        last_seen_at=now,
    )


class TestFindingStatusApi:
    def test_resolve_flips_status_and_stamps_resolved_at(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)

        api_client.force_authenticate(member)
        resp = api_client.post(_url(ws, finding), {"action": "resolve"}, format="json")

        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["status"] == "resolved"
        assert resp.data["data"]["changed"] is True
        finding.refresh_from_db()
        assert finding.status == "resolved"
        assert finding.resolved_at is not None

    def test_resolved_finding_drops_from_open_list(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)

        api_client.force_authenticate(member)
        api_client.post(_url(ws, finding), {"action": "resolve"}, format="json")

        open_items = api_client.get(f"/api/v1/findings/workspaces/{ws.id}/?status=open").data["data"]["items"]
        assert finding.id not in {UUID(f["id"]) for f in open_items}

    def test_suppress_dismisses_without_deleting_the_row(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)

        api_client.force_authenticate(member)
        resp = api_client.post(_url(ws, finding), {"action": "suppress"}, format="json")

        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["status"] == "suppressed"
        # Not a hard delete — the row is retained (auditable + re-observable).
        assert Finding.objects.filter(id=finding.id).exists()

    def test_reopen_returns_terminal_finding_to_open(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws, status="resolved")

        api_client.force_authenticate(member)
        resp = api_client.post(_url(ws, finding), {"action": "reopen"}, format="json")

        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["status"] == "open"
        finding.refresh_from_db()
        assert finding.status == "open"
        assert finding.resolved_at is None

    def test_invalid_action_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)

        api_client.force_authenticate(member)
        resp = api_client.post(_url(ws, finding), {"action": "nuke"}, format="json")
        assert resp.status_code == 400

    def test_missing_finding_is_404(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        finding.delete()

        api_client.force_authenticate(member)
        resp = api_client.post(_url(ws, finding), {"action": "resolve"}, format="json")
        assert resp.status_code == 404

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(user_factory())  # authenticated but not a member
        resp = api_client.post(_url(ws, finding), {"action": "resolve"}, format="json")
        assert resp.status_code == 403
        finding.refresh_from_db()
        assert finding.status == "open"  # unchanged

    def test_requires_authentication(self, api_client, workspace_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        assert api_client.post(_url(ws, finding), {"action": "resolve"}, format="json").status_code in (401, 403)

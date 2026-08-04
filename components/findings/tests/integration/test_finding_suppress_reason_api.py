"""Suppress with reason + optional expiry (ADR 0015 D9) — the status endpoint extension.

Fields persist to ``Finding.status_reason`` / ``Finding.suppress_expires_at``;
resolve/reopen clear them. Enforcement of the expiry (auto-reopen) is P2 — NOT here.
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


def _finding(ws, *, status="open"):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint="fp-suppress",
        asset_urn="arn:aws:s3:::bucket",
        severity="high",
        status=status,
        title="Public bucket",
        first_seen_at=now,
        last_seen_at=now,
    )


class TestSuppressReasonApi:
    def test_suppress_with_reason_and_expiry_persists(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(
            _url(ws, finding),
            {
                "action": "suppress",
                "reason": "vendor-accepted; sandboxed",
                "expires_at": "2026-11-01T00:00:00Z",
            },
            format="json",
        )
        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["status"] == "suppressed"
        finding.refresh_from_db()
        assert finding.status == "suppressed"
        assert finding.status_reason == "vendor-accepted; sandboxed"
        assert finding.suppress_expires_at is not None
        assert finding.suppress_expires_at.strftime("%Y-%m-%d") == "2026-11-01"

    def test_one_click_suppress_still_works(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws, finding), {"action": "suppress"}, format="json")
        assert resp.status_code == 200
        finding.refresh_from_db()
        assert finding.status_reason == ""
        assert finding.suppress_expires_at is None

    def test_reason_on_resolve_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws, finding), {"action": "resolve", "reason": "nope"}, format="json")
        assert resp.status_code == 400
        finding.refresh_from_db()
        assert finding.status == "open"  # unchanged

    def test_bad_expires_at_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws, finding), {"action": "suppress", "expires_at": "next tuesday"}, format="json")
        assert resp.status_code == 400

    def test_reopen_clears_reason_and_expiry(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        api_client.post(
            _url(ws, finding),
            {"action": "suppress", "reason": "temp", "expires_at": "2026-11-01T00:00:00Z"},
            format="json",
        )
        api_client.post(_url(ws, finding), {"action": "reopen"}, format="json")
        finding.refresh_from_db()
        assert finding.status == "open"
        assert finding.status_reason == ""
        assert finding.suppress_expires_at is None

    def test_list_serializes_suppress_context(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(_member(ws, user_factory))
        api_client.post(_url(ws, finding), {"action": "suppress", "reason": "accepted"}, format="json")
        rows = api_client.get(f"/api/v1/findings/workspaces/{ws.id}/?status=suppressed").data["data"]["items"]
        assert rows[0]["status_reason"] == "accepted"

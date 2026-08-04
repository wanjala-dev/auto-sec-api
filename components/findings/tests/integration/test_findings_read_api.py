"""Read API over the Finding SSOT — GET /api/v1/findings/workspaces/<ws>/.

Pins the surface that makes the unified findings spine visible: membership-gated,
workspace-scoped, filterable (severity/status/source), paginated, newest-first.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _url(ws, query=""):
    return f"/api/v1/findings/workspaces/{ws.id}/{query}"


def _member(ws, user_factory):
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    return member


def _finding(
    ws,
    *,
    source="logwatch.error",
    fingerprint="fp-1",
    severity="high",
    status="open",
    title="Internal Server Error",
    asset_urn=None,
    seen=None,
):
    now = seen or timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source=source,
        fingerprint=fingerprint,
        asset_urn=asset_urn or f"urn:log:{ws.id}/web",
        severity=severity,
        status=status,
        title=title,
        first_seen_at=now,
        last_seen_at=now,
    )


class TestFindingsReadApi:
    def test_lists_workspace_findings_newest_first(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        old = timezone.now() - timezone.timedelta(hours=2)
        _finding(ws, fingerprint="fp-old", title="older", seen=old)
        _finding(ws, fingerprint="fp-new", title="newer")

        api_client.force_authenticate(member)
        resp = api_client.get(_url(ws))

        assert resp.status_code == 200, resp.data
        data = resp.data["data"]
        assert data["total"] == 2
        assert [f["title"] for f in data["items"]] == ["newer", "older"]  # -last_seen_at
        first = data["items"][0]
        assert first["source"] == "logwatch.error"
        assert first["severity"] == "high"
        assert first["status"] == "open"
        assert first["is_open"] is True
        assert first["asset_urn"] == f"urn:log:{ws.id}/web"

    def test_filters_by_severity(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _finding(ws, fingerprint="fp-h", severity="high")
        _finding(ws, fingerprint="fp-c", severity="critical")

        api_client.force_authenticate(member)
        resp = api_client.get(_url(ws, "?severity=critical"))

        assert resp.status_code == 200, resp.data
        items = resp.data["data"]["items"]
        assert len(items) == 1
        assert items[0]["severity"] == "critical"

    def test_filters_by_source(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _finding(ws, fingerprint="fp-log", source="logwatch.error")
        _finding(ws, fingerprint="fp-cp", source="cloud_posture.prowler", asset_urn="arn:aws:s3:::b")

        api_client.force_authenticate(member)
        resp = api_client.get(_url(ws, "?source=cloud_posture.prowler"))

        items = resp.data["data"]["items"]
        assert len(items) == 1
        assert items[0]["source"] == "cloud_posture.prowler"

    def test_paginates_with_total(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        base = timezone.now()
        for i in range(3):
            _finding(ws, fingerprint=f"fp-{i}", title=f"f{i}", seen=base - timezone.timedelta(minutes=i))

        api_client.force_authenticate(member)
        page1 = api_client.get(_url(ws, "?limit=2")).data["data"]
        assert page1["total"] == 3
        assert len(page1["items"]) == 2
        assert page1["limit"] == 2 and page1["offset"] == 0

        page2 = api_client.get(_url(ws, "?limit=2&offset=2")).data["data"]
        assert page2["total"] == 3
        assert len(page2["items"]) == 1

    def test_scoped_to_workspace(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        other = workspace_factory()
        member = _member(ws, user_factory)
        _finding(ws, fingerprint="fp-mine")
        _finding(other, fingerprint="fp-theirs")

        api_client.force_authenticate(member)
        items = api_client.get(_url(ws)).data["data"]["items"]
        assert {f["fingerprint"] for f in items} == {"fp-mine"}

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        _finding(ws, fingerprint="fp-x")
        api_client.force_authenticate(user_factory())  # authenticated but not a member
        assert api_client.get(_url(ws)).status_code == 403

    def test_requires_authentication(self, api_client, workspace_factory):
        ws = workspace_factory()
        assert api_client.get(_url(ws)).status_code in (401, 403)

    def test_invalid_severity_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        assert api_client.get(_url(ws, "?severity=catastrophic")).status_code == 400

    def test_query_count_is_constant_wrt_rows(self, api_client, workspace_factory, user_factory):
        # No N+1 (performance rule §1/§11): the query count for a 1-row page must equal
        # the count for an 11-row page. select_related("workspace") + a flat resource keep
        # it constant (membership + list + count).
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        api_client.get(_url(ws))  # warm one-time caches (feature flags, content types)

        _finding(ws, fingerprint="fp-a")
        with CaptureQueriesContext(connection) as few:
            api_client.get(_url(ws))

        for i in range(10):
            _finding(ws, fingerprint=f"bulk-{i}")
        with CaptureQueriesContext(connection) as many:
            api_client.get(_url(ws))

        assert len(many.captured_queries) == len(few.captured_queries), [q["sql"] for q in many.captured_queries]


class TestFindingDetailApi:
    """GET /findings/workspaces/<ws>/<finding_id>/ — the deep-link read (a Slack
    alert's "View in Auto-Sec" opens the HUD on exactly this finding)."""

    def _detail_url(self, ws, finding_id):
        return f"/api/v1/findings/workspaces/{ws.id}/{finding_id}/"

    def test_member_reads_one_finding(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        row = _finding(ws, fingerprint="fp-one", title="Public S3 bucket")

        api_client.force_authenticate(member)
        resp = api_client.get(self._detail_url(ws, row.id))

        assert resp.status_code == 200, resp.data
        data = resp.data["data"]
        assert data["id"] == str(row.id)
        assert data["title"] == "Public S3 bucket"
        assert data["status"] == "open"
        assert "risk" in data  # same row shape as the list read (null until scored)
        assert data["risk"] is None
        assert data["tags"] == []

    def test_resolved_finding_still_renders_with_its_status(self, api_client, workspace_factory, user_factory):
        # A stale Slack link must show the finding honestly (resolved), not 404.
        ws = workspace_factory()
        member = _member(ws, user_factory)
        row = _finding(ws, fingerprint="fp-res", status="resolved")

        api_client.force_authenticate(member)
        resp = api_client.get(self._detail_url(ws, row.id))
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "resolved"

    def test_unknown_id_is_404(self, api_client, workspace_factory, user_factory):
        import uuid

        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        resp = api_client.get(self._detail_url(ws, uuid.uuid4()))
        assert resp.status_code == 404
        assert resp.data["error"] == "not_found"

    def test_other_workspaces_finding_is_404(self, api_client, workspace_factory, user_factory):
        # Workspace-scoped by construction: an id from another tenant never resolves.
        ws = workspace_factory()
        other = workspace_factory()
        member = _member(ws, user_factory)
        theirs = _finding(other, fingerprint="fp-theirs")

        api_client.force_authenticate(member)
        assert api_client.get(self._detail_url(ws, theirs.id)).status_code == 404

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        row = _finding(ws, fingerprint="fp-x")
        api_client.force_authenticate(user_factory())
        assert api_client.get(self._detail_url(ws, row.id)).status_code == 403

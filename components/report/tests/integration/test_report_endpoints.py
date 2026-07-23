"""HTTP-boundary tests for the report controllers.

Drives the real DRF views + permissions + repository through the API client.
Locks the endpoint contract: 202 on generate (with a Celery dispatch stubbed at
the task boundary), list scoping, the owner/admin approve role-gate (403 for a
plain member), and download blocked until approved.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(user_factory):
    return user_factory(username="rpt-owner", email="rpt-owner@example.com")


@pytest.fixture
def member(user_factory):
    return user_factory(username="rpt-member", email="rpt-member@example.com")


@pytest.fixture
def outsider(user_factory):
    return user_factory(username="rpt-outsider", email="rpt-outsider@example.com")


@pytest.fixture
def workspace(workspace_factory, owner):
    return workspace_factory(owner=owner)


@pytest.fixture
def member_client(workspace, member):
    """A plain (non-owner) MEMBER of the workspace."""
    from infrastructure.persistence.workspaces.models import WorkspaceMembership

    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMembership.Role.MEMBER,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(member)
    return client


@pytest.fixture
def owner_client(owner):
    client = APIClient()
    client.force_authenticate(owner)
    return client


def _ws(workspace):
    return str(workspace.id)


def _seed_report(workspace, *, status="generated", pdf_key="k.pdf"):
    from infrastructure.persistence.report.models import Report

    return Report.objects.create(
        workspace=workspace,
        kind="pentest",
        title="Seeded Report",
        status=status,
        pdf_key=pdf_key,
        finding_count=2,
    )


class TestKinds:
    def test_kinds_lists_pentest(self, owner_client):
        resp = owner_client.get("/report/kinds/")
        assert resp.status_code == 200
        ids = {k["id"] for k in resp.json()["kinds"]}
        assert "pentest" in ids


class TestGenerate:
    def test_generate_returns_202(self, owner_client, workspace, monkeypatch):
        dispatched = {}

        def fake_delay(**kwargs):
            dispatched.update(kwargs)

        monkeypatch.setattr("components.report.workers.tasks.generate_report.delay", fake_delay)

        resp = owner_client.post(
            f"/report/generate/?workspace={_ws(workspace)}",
            {"kind": "pentest", "title": "Q3 Pentest", "scope": {"scope_summary": "web + cloud"}},
            format="json",
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "draft"
        assert body["kind"] == "pentest"
        assert body["title"] == "Q3 Pentest"
        # The async generation was enqueued with the new report id.
        assert dispatched["report_id"] == body["id"]
        assert dispatched["workspace_id"] == _ws(workspace)

    def test_generate_rejects_unknown_kind(self, owner_client, workspace):
        resp = owner_client.post(
            f"/report/generate/?workspace={_ws(workspace)}",
            {"kind": "made-up"},
            format="json",
        )
        assert resp.status_code == 400

    def test_outsider_cannot_generate(self, workspace, outsider):
        client = APIClient()
        client.force_authenticate(outsider)
        resp = client.post(f"/report/generate/?workspace={_ws(workspace)}", {"kind": "pentest"}, format="json")
        assert resp.status_code == 403


class TestList:
    def test_list_scoped_to_workspace(self, owner_client, workspace):
        _seed_report(workspace)
        resp = owner_client.get(f"/report/?workspace={_ws(workspace)}")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["title"] == "Seeded Report"


class TestApproveRoleGate:
    def test_owner_can_approve(self, owner_client, workspace):
        report = _seed_report(workspace, status="generated")
        resp = owner_client.post(f"/report/{report.id}/approve/?workspace={_ws(workspace)}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_plain_member_is_forbidden(self, member_client, workspace):
        report = _seed_report(workspace, status="generated")
        resp = member_client.post(f"/report/{report.id}/approve/?workspace={_ws(workspace)}")
        assert resp.status_code == 403

    def test_cannot_approve_a_draft(self, owner_client, workspace):
        report = _seed_report(workspace, status="draft")
        resp = owner_client.post(f"/report/{report.id}/approve/?workspace={_ws(workspace)}")
        assert resp.status_code == 409


class TestDownloadGate:
    def test_download_blocked_until_approved(self, owner_client, workspace):
        report = _seed_report(workspace, status="generated")
        resp = owner_client.get(f"/report/{report.id}/download/?workspace={_ws(workspace)}")
        assert resp.status_code == 409

    def test_download_redirects_once_approved(self, owner_client, workspace, monkeypatch):
        report = _seed_report(workspace, status="approved", pdf_key=f"{_ws(workspace)}/{{}}.pdf")

        monkeypatch.setattr(
            "components.report.infrastructure.services.report_pdf_storage_service.ReportPdfStorageService.presigned_url",
            lambda self, *, key, filename=None: "https://minio.local/signed",
        )
        resp = owner_client.get(f"/report/{report.id}/download/?workspace={_ws(workspace)}")
        assert resp.status_code == 302
        assert resp["Location"] == "https://minio.local/signed"

    def test_inline_preview_allowed_for_generated_draft(self, owner_client, workspace, monkeypatch):
        # A GENERATED (not-yet-approved) report can be previewed inline so a
        # reviewer reads the draft before signing off.
        report = _seed_report(workspace, status="generated", pdf_key=f"{_ws(workspace)}/{{}}.pdf")
        captured = {}

        def _fake_presign(self, *, key, filename=None):
            captured["filename"] = filename
            return "https://minio.local/signed-inline"

        monkeypatch.setattr(
            "components.report.infrastructure.services.report_pdf_storage_service.ReportPdfStorageService.presigned_url",
            _fake_presign,
        )
        resp = owner_client.get(f"/report/{report.id}/download/?workspace={_ws(workspace)}&inline=1")
        assert resp.status_code == 302
        assert resp["Location"] == "https://minio.local/signed-inline"
        assert captured["filename"] is None  # inline preview carries no attachment filename

    def test_inline_preview_blocked_before_generated(self, owner_client, workspace):
        report = _seed_report(workspace, status="draft")
        resp = owner_client.get(f"/report/{report.id}/download/?workspace={_ws(workspace)}&inline=1")
        assert resp.status_code == 409

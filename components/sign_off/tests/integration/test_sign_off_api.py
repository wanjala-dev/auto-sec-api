"""End-to-end coverage of the unified sign-off queue API (Phase 6a).

Drives the real registered adapters (reports + content + workflow, wired in
their app ``ready()`` hooks) through the HTTP surface: a workspace member sees
pending artifacts across every type; a non-member is denied; and the RED gate
blocks a one-click approve of a contradicted report.
"""

from __future__ import annotations

from datetime import date

import pytest
from rest_framework.test import APIClient

from infrastructure.persistence.content.models import Newsletter, WritingDraft
from infrastructure.persistence.reports.models import FinancialReport
from infrastructure.persistence.users.models import CustomUser
from infrastructure.persistence.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return CustomUser.objects.create_user(
        username="signoff-owner", email="signoff-owner@example.com", password="pw123456"
    )


@pytest.fixture
def outsider():
    return CustomUser.objects.create_user(
        username="signoff-outsider", email="signoff-outsider@example.com", password="pw123456"
    )


@pytest.fixture
def workspace(owner):
    return Workspace.objects.create(
        workspace_name="Signoff WS", workspace_owner=owner, status="active"
    )


def _seed_pending(workspace, owner):
    report = FinancialReport.objects.create(
        workspace=workspace,
        report_type=FinancialReport.REPORT_TYPE_MONTHLY,
        variant="impact",
        title="Impact report",
        content="Thank you.",
        payload={},
        date_start=date(2024, 1, 1),
        date_end=date(2024, 1, 31),
        review_state="pending",
    )
    newsletter = Newsletter.objects.create(
        workspace=workspace, title="Weekly", status="ai_drafted", content_html="<p>Hi</p>"
    )
    draft = WritingDraft.objects.create(
        workspace=workspace,
        title="Letter",
        body_html="<p>Dear donor</p>",
        kind="letter",
        status="draft",
        author=owner,
        ai_drafted=True,
    )
    return report, newsletter, draft


def test_pending_lists_items_across_types_for_a_member(workspace, owner):
    _seed_pending(workspace, owner)
    client = APIClient()
    client.force_authenticate(user=owner)

    resp = client.get("/sign-off/pending/", {"workspace_id": str(workspace.id)})

    assert resp.status_code == 200
    results = resp.data["results"] if "results" in resp.data else resp.data
    types = {row["artifact_type"] for row in results}
    assert {"financial_report", "newsletter", "writing_draft"} <= types


def test_pending_requires_workspace_id(workspace, owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    resp = client.get("/sign-off/pending/")
    assert resp.status_code == 400


def test_pending_denies_non_member(workspace, owner, outsider):
    _seed_pending(workspace, owner)
    client = APIClient()
    client.force_authenticate(user=outsider)

    resp = client.get("/sign-off/pending/", {"workspace_id": str(workspace.id)})
    assert resp.status_code == 403


def test_approve_red_report_without_reason_is_blocked(workspace, owner):
    # annual variant (high stakes) + an unverifiable figure -> RED band.
    report = FinancialReport.objects.create(
        workspace=workspace,
        report_type=FinancialReport.REPORT_TYPE_ANNUAL,
        variant="annual",
        title="Annual",
        content="We raised $999,999 this year.",
        payload={},
        date_start=date(2024, 1, 1),
        date_end=date(2024, 12, 31),
        review_state="pending",
    )
    client = APIClient()
    client.force_authenticate(user=owner)

    resp = client.post(f"/sign-off/financial_report/{report.id}/approve/", {}, format="json")

    assert resp.status_code in (400, 409)
    report.refresh_from_db()
    assert report.review_state == "pending"  # gate held


def test_detail_returns_receipts_for_a_member(workspace, owner):
    report, _, _ = _seed_pending(workspace, owner)
    client = APIClient()
    client.force_authenticate(user=owner)

    resp = client.get(f"/sign-off/financial_report/{report.id}/")
    assert resp.status_code == 200
    assert resp.data["artifact_type"] == "financial_report"
    assert "receipts" in resp.data
    assert "figure_checks" in resp.data["receipts"]

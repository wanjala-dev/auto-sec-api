"""End-to-end coverage of the unified sign-off queue API (Phase 6a).

Drives the real registered adapters through the HTTP surface: a workspace
member sees pending artifacts across every type, and a non-member is denied.

THIS MODULE DID NOT RUN. It imported ``infrastructure.persistence.reports``,
the nonprofit financial-reporting app the fork removed, so it raised
ModuleNotFoundError at COLLECTION time — which does not fail one test, it
aborts collection for the whole ``components/sign_off/tests/`` directory.
Every sign-off test in the repo was therefore unrunnable by the obvious
command, which is part of why a completely broken audit trail sat here
unnoticed. A test that cannot be collected is worse than no test: it looks
like coverage in the file listing and reports nothing.

Rewritten around the artifact types that still exist — ``newsletter`` and
``writing_draft``, both registered by the content context. The two
``financial_report`` cases are not ported: the RED-gate assertion is already
covered at the service level in
``tests/unit/test_sign_off_queue_service.py::test_red_approve_without_reason_raises_and_does_not_delegate``,
and the receipts-detail assertion referenced report-specific ``figure_checks``.
Re-establishing an HTTP-level RED-gate case on a surviving artifact type is
worth doing and is NOT done here.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from infrastructure.persistence.content.models import Newsletter, WritingDraft
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
    return Workspace.objects.create(workspace_name="Signoff WS", workspace_owner=owner, status="active")


def _seed_pending(workspace, owner):
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
    return newsletter, draft


def test_pending_lists_items_across_types_for_a_member(workspace, owner):
    _seed_pending(workspace, owner)
    client = APIClient()
    client.force_authenticate(user=owner)

    resp = client.get("/sign-off/pending/", {"workspace_id": str(workspace.id)})

    assert resp.status_code == 200
    results = resp.data["results"] if "results" in resp.data else resp.data
    types = {row["artifact_type"] for row in results}
    assert {"newsletter", "writing_draft"} <= types


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


def test_detail_returns_receipts_for_a_member(workspace, owner):
    newsletter, _ = _seed_pending(workspace, owner)
    client = APIClient()
    client.force_authenticate(user=owner)

    resp = client.get(f"/sign-off/newsletter/{newsletter.id}/")

    assert resp.status_code == 200
    assert resp.data["artifact_type"] == "newsletter"
    assert "receipts" in resp.data

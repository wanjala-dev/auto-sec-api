"""Integration tests for the opt-in document-index endpoint.

POST /upload/<file_id>/index/ is the explicit gate into the workspace
RAG store: membership-checked, quota-metered, breaker-protected, and the
retry path for failed indexing. The PDF-chat surface refuses un-indexed
documents with the action the user needs to take.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from infrastructure.persistence.uploads.models import File

pytestmark = pytest.mark.django_db


def _file(owner, workspace_id, *, status="not_indexed", file_type="pdf", requested_at=None):
    return File.objects.create(
        owner=owner,
        workspace_id=workspace_id,
        file=SimpleUploadedFile("doc.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
        file_type=file_type,
        processing_status=status,
        index_requested_at=requested_at,
    )


@pytest.fixture()
def member(api_client, user_factory, workspace_factory):
    user = user_factory()
    ws = workspace_factory(owner=user)
    api_client.force_authenticate(user=user)
    return SimpleNamespace(user=user, ws=ws, client=api_client)


@pytest.fixture()
def _configured(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture()
def _task(monkeypatch):
    called = {"count": 0}

    def _fake_delay(file_id):
        called["count"] += 1
        return SimpleNamespace(id="task-123")

    monkeypatch.setattr("uploads.tasks.process_pdf_file.delay", _fake_delay)
    return called


class TestIndexEndpoint:
    def test_index_dispatches_and_stamps_the_request(self, member, _configured, _task):
        doc = _file(member.user, str(member.ws.id))

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 202
        assert response.data["processing_status"] == "pending"
        doc.refresh_from_db()
        assert doc.processing_status == "pending"
        assert doc.index_requested_at is not None
        assert _task["count"] == 1

    def test_failed_document_can_retry(self, member, _configured, _task):
        doc = _file(member.user, str(member.ws.id), status="failed")

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 202
        assert _task["count"] == 1

    def test_already_indexed_is_a_successful_noop(self, member, _configured, _task):
        doc = _file(member.user, str(member.ws.id), status="completed")

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 200
        assert response.data["dispatched"] is False
        assert _task["count"] == 0

    def test_daily_quota_refuses_with_429(self, member, _configured, _task, monkeypatch):
        monkeypatch.setenv("DOCUMENT_INDEX_DAILY_CAP", "2")
        recent = timezone.now() - timedelta(hours=1)
        _file(member.user, str(member.ws.id), status="completed", requested_at=recent)
        _file(member.user, str(member.ws.id), status="pending", requested_at=recent)
        doc = _file(member.user, str(member.ws.id))

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 429
        assert response.data["code"] == "quota_exceeded"
        assert _task["count"] == 0

    def test_breaker_pauses_after_consecutive_failures(self, member, _configured, _task):
        recent = timezone.now() - timedelta(minutes=10)
        for _ in range(5):
            _file(member.user, str(member.ws.id), status="failed", requested_at=recent)
        doc = _file(member.user, str(member.ws.id))

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 503
        assert response.data["code"] == "indexing_paused"
        assert _task["count"] == 0

    def test_unconfigured_environment_refuses_loudly(self, member, _task, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        doc = _file(member.user, str(member.ws.id))

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 503
        assert response.data["code"] == "not_configured"

    def test_non_member_is_denied(self, api_client, user_factory, workspace_factory, _configured):
        owner, stranger = user_factory(), user_factory()
        ws = workspace_factory(owner=owner)
        doc = _file(owner, str(ws.id))
        api_client.force_authenticate(user=stranger)

        response = api_client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(ws.id)}, format="json"
        )

        assert response.status_code == 403

    def test_other_workspaces_file_is_404(self, member, _configured, user_factory, workspace_factory):
        other_owner = user_factory()
        other_ws = workspace_factory(owner=other_owner)
        doc = _file(other_owner, str(other_ws.id))

        response = member.client.post(
            f"/api/v1/upload/{doc.id}/index/", {"workspace_id": str(member.ws.id)}, format="json"
        )

        assert response.status_code == 404


class TestPdfChatRequiresIndexing:
    def test_un_indexed_document_conversation_is_refused(self, member):
        doc = _file(member.user, str(member.ws.id), status="not_indexed")

        response = member.client.post(
            "/api/v1/ai/conversations/",
            {"pdf_id": doc.id, "workspace_id": str(member.ws.id)},
            format="json",
        )

        assert response.status_code == 409
        assert response.data["code"] == "document_not_indexed"
        assert "Index this document" in response.data["error"]

    def test_indexed_document_conversation_creates(self, member):
        doc = _file(member.user, str(member.ws.id), status="completed")

        response = member.client.post(
            "/api/v1/ai/conversations/",
            {"pdf_id": doc.id, "workspace_id": str(member.ws.id)},
            format="json",
        )

        assert response.status_code == 201

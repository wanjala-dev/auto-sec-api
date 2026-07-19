"""Tests for the uploads API."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from docx import Document as DocxDocument
from rest_framework import status

from infrastructure.persistence.uploads.models import File

pytestmark = pytest.mark.django_db


def _make_test_pdf() -> SimpleUploadedFile:
    """Return a minimal PDF payload recognised by the view."""
    pdf_bytes = b"%PDF-1.4\n% Fake PDF content for testing\n"
    return SimpleUploadedFile("document.pdf", pdf_bytes, content_type="application/pdf")


def _make_test_docx() -> SimpleUploadedFile:
    """Return a tiny docx payload for upload tests."""
    buffer = BytesIO()
    doc = DocxDocument()
    doc.add_paragraph("Hello from a test docx file.")
    doc.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        "document.docx",
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _make_test_csv() -> SimpleUploadedFile:
    """Return a simple CSV payload for upload tests."""
    csv_bytes = b"col1,col2\nvalue1,value2\n"
    return SimpleUploadedFile("data.csv", csv_bytes, content_type="text/csv")


def _stub_task(monkeypatch, path: str):
    """Patch a Celery task .delay call to avoid real processing and capture the ID."""
    called = {"count": 0, "file_id": None}

    def _fake_delay(file_id):
        called["file_id"] = file_id
        called["count"] += 1
        return SimpleNamespace(id="task-123", state="PENDING")

    monkeypatch.setattr(path, _fake_delay)
    return called


def test_plain_pdf_upload_lands_not_indexed(api_client, user_factory, monkeypatch):
    """Indexing is opt-in: a plain upload creates the File record and
    dispatches NOTHING — it waits for an explicit index request."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    task_call = _stub_task(monkeypatch, "uploads.tasks.process_pdf_file.delay")

    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_pdf(), "workspace_id": "workspace-123"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get()
    assert file_obj.owner == user
    assert file_obj.file_type == "pdf"
    assert response.data["processing_status"] == "not_indexed"
    assert file_obj.processing_status == "not_indexed"
    assert task_call["count"] == 0


def test_pdf_upload_with_index_intent_dispatches(api_client, user_factory, monkeypatch):
    """The AI-grounding uploader passes index=true — that IS the explicit
    request, so the embed task dispatches through the opt-in policy."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    task_call = _stub_task(monkeypatch, "uploads.tasks.process_pdf_file.delay")

    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_pdf(), "workspace_id": "workspace-123", "index": "true"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get()
    assert response.data["processing_status"] == "pending"
    assert file_obj.index_requested_at is not None
    assert task_call["count"] == 1
    assert task_call["file_id"] == file_obj.id


def test_anonymous_user_cannot_upload(api_client):
    """Unauthenticated requests are rejected with 401."""
    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_pdf(), "workspace_id": "workspace-123"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert File.objects.count() == 0


def test_authenticated_user_can_upload_docx(api_client, user_factory, monkeypatch):
    """Authenticated requests can upload docx documents for embedding."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    task_call = _stub_task(monkeypatch, "uploads.tasks.process_document_file.delay")

    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_docx(), "workspace_id": "workspace-123"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get()
    assert file_obj.file_type == "document"
    assert file_obj.owner == user
    assert response.data["processing_status"] == "not_indexed"
    assert task_call["count"] == 0


def test_authenticated_user_can_upload_csv(api_client, user_factory, monkeypatch):
    """Authenticated requests can upload CSV documents for embedding."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    task_call = _stub_task(monkeypatch, "uploads.tasks.process_document_file.delay")

    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_csv(), "workspace_id": "workspace-123"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get()
    assert file_obj.file_type == "document"
    assert file_obj.owner == user
    assert response.data["processing_status"] == "not_indexed"
    assert task_call["count"] == 0


def test_rejects_unknown_content_type(api_client, user_factory):
    """Non-whitelisted mime types return 415."""
    user = user_factory()
    api_client.force_authenticate(user=user)
    payload = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")

    response = api_client.post(
        reverse("files_list"),
        {"file": payload, "workspace_id": "workspace-123"},
        format="multipart",
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert File.objects.count() == 0


def test_workspace_id_is_required(api_client, user_factory):
    """workspace_id must be present to create a File."""
    user = user_factory()
    api_client.force_authenticate(user=user)

    response = api_client.post(
        reverse("files_list"),
        {"file": _make_test_pdf()},
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert File.objects.count() == 0

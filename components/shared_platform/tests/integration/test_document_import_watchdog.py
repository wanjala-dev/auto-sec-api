"""Integration tests for the stuck-import watchdog + retry flow.

Covers the resilience contract we advertise to the frontend:
  - A Celery worker crash mid-parse must not leave an import in
    ``parsing`` forever.
  - The watchdog re-enqueues up to ``MAX_AUTO_RETRIES`` times.
  - Past that, it transitions the import to ``failed`` with a clear
    message.
  - The ``/imports/<id>/retry/`` endpoint lets the frontend escape
    manually from any stuck or failed state.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone


@pytest.fixture
def DocumentImport():
    return django_apps.get_model("imports", "DocumentImport")


@pytest.fixture
def File():
    return django_apps.get_model("uploads", "File")


def _make_import(
    *,
    DocumentImport,
    File,
    workspace,
    user,
    status,
    last_heartbeat_at=None,
    created_at=None,
    retry_count=0,
    attach_file=True,
):
    source_file = None
    if attach_file:
        source_file = File.objects.create(owner=user)
    imp = DocumentImport.objects.create(
        workspace=workspace,
        uploaded_by=user,
        source_file=source_file,
        original_filename="test.csv",
        import_type=DocumentImport.TYPE_EXPENSE,
        status=status,
        last_heartbeat_at=last_heartbeat_at,
        retry_count=retry_count,
    )
    if created_at is not None:
        DocumentImport.objects.filter(pk=imp.pk).update(created_at=created_at)
        imp.refresh_from_db()
    return imp


@pytest.mark.django_db
class TestSweepStuckDocumentImports:
    def test_retries_stuck_import_with_stale_heartbeat(
        self, DocumentImport, File, workspace_factory, user_factory, monkeypatch
    ):
        from components.shared_platform.infrastructure.tasks import (
            document_import_tasks,
        )

        workspace = workspace_factory()
        user = user_factory()
        stale = timezone.now() - timedelta(minutes=30)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_PARSING,
            last_heartbeat_at=stale,
            retry_count=0,
        )

        scheduled_ids = []
        monkeypatch.setattr(
            document_import_tasks.document_import_parse,
            "delay",
            lambda pk: scheduled_ids.append(pk),
        )

        result = document_import_tasks.sweep_stuck_document_imports()

        imp.refresh_from_db()
        assert result == {"retried": 1, "failed": 0}
        assert imp.status == DocumentImport.STATUS_PENDING
        assert imp.retry_count == 1
        assert imp.last_heartbeat_at is None
        assert scheduled_ids == [imp.pk]

    def test_fails_after_max_retries(
        self, DocumentImport, File, workspace_factory, user_factory, monkeypatch
    ):
        from components.shared_platform.infrastructure.tasks import (
            document_import_tasks,
        )

        workspace = workspace_factory()
        user = user_factory()
        stale = timezone.now() - timedelta(minutes=30)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_PARSING,
            last_heartbeat_at=stale,
            retry_count=document_import_tasks.MAX_AUTO_RETRIES,
        )

        monkeypatch.setattr(
            document_import_tasks.document_import_parse,
            "delay",
            lambda pk: None,
        )

        result = document_import_tasks.sweep_stuck_document_imports()

        imp.refresh_from_db()
        assert result == {"retried": 0, "failed": 1}
        assert imp.status == DocumentImport.STATUS_FAILED
        assert "stalled" in imp.error_message.lower()

    def test_leaves_alive_imports_untouched(
        self, DocumentImport, File, workspace_factory, user_factory, monkeypatch
    ):
        """A recent heartbeat means the parse is still making progress."""
        from components.shared_platform.infrastructure.tasks import (
            document_import_tasks,
        )

        workspace = workspace_factory()
        user = user_factory()
        fresh = timezone.now() - timedelta(minutes=2)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_PARSING,
            last_heartbeat_at=fresh,
        )

        monkeypatch.setattr(
            document_import_tasks.document_import_parse,
            "delay",
            lambda pk: None,
        )

        result = document_import_tasks.sweep_stuck_document_imports()

        imp.refresh_from_db()
        assert result == {"retried": 0, "failed": 0}
        assert imp.status == DocumentImport.STATUS_PARSING


@pytest.mark.django_db
class TestDocumentImportRetryEndpoint:
    def _force_login(self, api_client, user, workspace):
        api_client.force_authenticate(user=user)
        # The endpoint uses ``IsOrgOwnerOrMember`` — owning the workspace
        # covers both sides of that permission.

    def test_retry_resets_failed_import_and_enqueues(
        self,
        api_client,
        DocumentImport,
        File,
        workspace_factory,
        user_factory,
        monkeypatch,
    ):
        from components.shared_platform.infrastructure.tasks import (
            document_import_tasks,
        )

        user = user_factory()
        workspace = workspace_factory(owner=user)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_FAILED,
            retry_count=2,
        )
        DocumentImport.objects.filter(pk=imp.pk).update(
            error_message="previous crash"
        )

        scheduled_ids = []
        monkeypatch.setattr(
            document_import_tasks.document_import_parse,
            "delay",
            lambda pk: scheduled_ids.append(pk),
        )

        self._force_login(api_client, user, workspace)
        url = reverse("document-import-retry", kwargs={"import_id": imp.pk})
        response = api_client.post(url)

        assert response.status_code == 202
        imp.refresh_from_db()
        assert imp.status == DocumentImport.STATUS_PENDING
        assert imp.retry_count == 3
        assert imp.error_message == ""
        assert imp.last_heartbeat_at is None
        assert scheduled_ids == [imp.pk]

    def test_retry_rejects_completed_imports(
        self,
        api_client,
        DocumentImport,
        File,
        workspace_factory,
        user_factory,
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_APPLIED,
        )
        self._force_login(api_client, user, workspace)
        response = api_client.post(
            reverse("document-import-retry", kwargs={"import_id": imp.pk})
        )
        assert response.status_code == 400
        imp.refresh_from_db()
        assert imp.status == DocumentImport.STATUS_APPLIED

    def test_retry_rejects_import_without_source_file(
        self,
        api_client,
        DocumentImport,
        File,
        workspace_factory,
        user_factory,
    ):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_FAILED,
            attach_file=False,
        )
        self._force_login(api_client, user, workspace)
        response = api_client.post(
            reverse("document-import-retry", kwargs={"import_id": imp.pk})
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestDocumentImportSerializer:
    def test_is_retryable_true_for_failed_with_source(
        self, DocumentImport, File, workspace_factory, user_factory
    ):
        from components.shared_platform.mappers.rest.document_import_serializers import (
            DocumentImportSerializer,
        )

        user = user_factory()
        workspace = workspace_factory(owner=user)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_FAILED,
        )
        data = DocumentImportSerializer(imp).data
        assert data["is_retryable"] is True
        assert data["retry_count"] == 0

    def test_is_retryable_false_for_applied(
        self, DocumentImport, File, workspace_factory, user_factory
    ):
        from components.shared_platform.mappers.rest.document_import_serializers import (
            DocumentImportSerializer,
        )

        user = user_factory()
        workspace = workspace_factory(owner=user)
        imp = _make_import(
            DocumentImport=DocumentImport,
            File=File,
            workspace=workspace,
            user=user,
            status=DocumentImport.STATUS_APPLIED,
        )
        data = DocumentImportSerializer(imp).data
        assert data["is_retryable"] is False

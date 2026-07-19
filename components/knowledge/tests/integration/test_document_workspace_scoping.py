"""Tier 2 #4 + #4a — ``Document`` rows are tenant-scoped at the DB layer.

Pre-Tier-2 the upload endpoint accepted documents without a
``workspace_id`` — they landed as orphan rows that any other workspace
could in principle read.  Tier 2 #4 (PR #280) added the FK as nullable
so the migration didn't block on existing orphan rows; Tier 2 #4a
shipped a one-shot audit (PR #343, now removed in the migration that
closes the loop) and the schema flip to ``NOT NULL`` in migration
0013.  These tests pin the four-part contract:

* The model has a **required** ``workspace`` FK.
* The repository accepts a ``workspace_id`` keyword and persists the
  FK on the row.
* The service refuses to create a document without a
  ``workspace_id`` — raises a ``ValueError`` rather than silently
  dropping tenant scope.
* The upload controller rejects requests without a ``workspace_id``
  with HTTP 400.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #4 / #4a.
"""
from __future__ import annotations

import pytest

from components.knowledge.application.service import KnowledgeService
from components.knowledge.infrastructure.repositories.document_repository import (
    OrmDocumentRepository,
)
from infrastructure.persistence.ai.models import Document


@pytest.mark.django_db
class TestDocumentModelHasWorkspaceField:
    def test_document_model_declares_workspace_fk(self):
        # Tier 2 #4a closed: the FK is NOT NULL at the schema level
        # now that the audit (PR #343) confirmed prod was clean.
        # Pre-Tier-2 orphan rows are gone; the schema constraint
        # enforces what the app boundary already required.
        field = Document._meta.get_field("workspace")
        assert field.null is False, (
            "Document.workspace must be non-nullable. The audit + "
            "cleanup landed in PR #343; migration 0013 flipped the "
            "schema constraint. Reverting to nullable re-opens the "
            "Tier 2 #4 tenant-scoping hole."
        )
        related = field.related_model
        assert related._meta.model_name == "workspace"
        assert field.remote_field.related_name == "documents", (
            "workspace.documents.all() is the tenant-scoped reverse "
            "accessor downstream Tier 2 #5/#6 work will use."
        )

    def test_workspace_documents_index_exists(self):
        index_names = {idx.name for idx in Document._meta.indexes}
        assert "ai_doc_ws_created_idx" in index_names, (
            "Composite (workspace, -created_at) index is required to "
            "support tenant-scoped 'list this workspace's documents "
            "newest first' queries efficiently."
        )


@pytest.mark.django_db
class TestRepositoryPersistsWorkspaceFk:
    def test_create_with_workspace_id_attaches_fk(self, workspace_factory):
        workspace = workspace_factory()
        document = OrmDocumentRepository().create(
            title="Mission brief",
            content="Body content.",
            source="upload",
            metadata={"kind": "test"},
            workspace_id=str(workspace.id),
        )
        document.refresh_from_db()
        assert str(document.workspace_id) == str(workspace.id)


@pytest.mark.django_db
class TestServiceRefusesMissingWorkspace:
    def test_create_document_without_workspace_id_raises_value_error(self):
        service = KnowledgeService()
        with pytest.raises(ValueError, match="workspace_id"):
            service.create_document(
                title="No tenant",
                content="Body.",
                source="upload",
                metadata={},
                workspace_id="",
            )

    def test_create_document_with_workspace_id_persists_fk(self, workspace_factory):
        service = KnowledgeService()
        workspace = workspace_factory()
        document = service.create_document(
            title="Tenant scoped",
            content="Body.",
            source="upload",
            metadata={"kind": "test"},
            workspace_id=str(workspace.id),
        )
        document.refresh_from_db()
        assert str(document.workspace_id) == str(workspace.id)


@pytest.mark.django_db
class TestUploadControllerRequiresWorkspace:
    @staticmethod
    def _make_admin(user):
        # The endpoint inherits DRF's DEFAULT_PERMISSION_CLASSES which
        # in this project is IsAdminUser + IsAuthenticated.  Promoting
        # the user to staff is the cheapest way to reach the
        # controller body — the test is about workspace_id enforcement,
        # not about the perms layer.
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        return user

    def _post(self, api_client, user, payload):
        api_client.force_authenticate(user=self._make_admin(user))
        return api_client.post(
            "/ai/vector_stores/",
            payload,
            format="json",
        )

    def test_upload_without_workspace_id_returns_400(
        self, api_client, user_factory
    ):
        response = self._post(
            api_client,
            user_factory(),
            {"title": "No tenant", "content": "Body."},
        )
        assert response.status_code == 400
        assert "workspace_id" in (response.data.get("error") or "").lower()

    def test_upload_with_workspace_id_at_top_level_persists(
        self, api_client, user_factory, workspace_factory
    ):
        workspace = workspace_factory()
        response = self._post(
            api_client,
            user_factory(),
            {
                "title": "Tenant scoped",
                "content": "Body.",
                "workspace_id": str(workspace.id),
            },
        )
        assert response.status_code == 200, response.data
        document = Document.objects.get(id=response.data["document_id"])
        assert str(document.workspace_id) == str(workspace.id)

    def test_upload_with_workspace_id_in_metadata_also_persists(
        self, api_client, user_factory, workspace_factory
    ):
        workspace = workspace_factory()
        response = self._post(
            api_client,
            user_factory(),
            {
                "title": "Tenant scoped via metadata",
                "content": "Body.",
                "metadata": {"workspace_id": str(workspace.id)},
            },
        )
        assert response.status_code == 200, response.data
        document = Document.objects.get(id=response.data["document_id"])
        assert str(document.workspace_id) == str(workspace.id)


@pytest.mark.django_db
class TestTenantIsolationOnRead:
    def test_workspace_documents_reverse_accessor_isolates_rows(
        self, user_factory, workspace_factory
    ):
        workspace_a = workspace_factory()
        workspace_b = workspace_factory()
        service = KnowledgeService()
        service.create_document(
            title="A",
            content="In workspace A.",
            source="upload",
            metadata={},
            workspace_id=str(workspace_a.id),
        )
        service.create_document(
            title="B",
            content="In workspace B.",
            source="upload",
            metadata={},
            workspace_id=str(workspace_b.id),
        )

        a_titles = list(workspace_a.documents.values_list("title", flat=True))
        b_titles = list(workspace_b.documents.values_list("title", flat=True))

        assert a_titles == ["A"], (
            "workspace.documents must only return rows tagged to that "
            "workspace — cross-tenant leakage is the privacy bug Tier "
            "2 #4 exists to close."
        )
        assert b_titles == ["B"]

"""API views for the shared document import pipeline.

Endpoints:
    POST   /imports/                          — Create import (upload file, queue task)
    GET    /imports/?workspace={id}            — List imports for workspace
    GET    /imports/{id}/                      — Import detail + status
    GET    /imports/{id}/rows/                 — List parsed rows
    PATCH  /imports/{id}/rows/{row_id}/        — Edit a row
    DELETE /imports/{id}/rows/{row_id}/        — Remove a row
    POST   /imports/{id}/apply/               — Apply approved rows
"""

from __future__ import annotations

import logging
import os

from components.shared_kernel.application.providers.django_orm_provider import (
    get_django_orm_provider as _get_django_orm_provider,
)

_django_orm = _get_django_orm_provider()
transaction = _django_orm.transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_platform.application.providers.imports_models_provider import (
    get_imports_models_provider,
)
from components.workspace.api.permissions import IsOrgOwnerOrMember

DocumentImport = get_imports_models_provider().DocumentImport
DocumentImportRow = get_imports_models_provider().DocumentImportRow
from components.shared_platform.mappers.rest.document_import_serializers import (
    DocumentImportCreateSerializer,
    DocumentImportRowSerializer,
    DocumentImportSerializer,
)

logger = logging.getLogger(__name__)


class DocumentImportListCreateView(APIView):
    """List imports for a workspace, or create a new one."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-list-create"

    def get(self, request):
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            return Response({"error": "workspace query param required"}, status=400)
        qs = DocumentImport.objects.filter(workspace_id=workspace_id)

        import_type = request.query_params.get("type")
        if import_type:
            qs = qs.filter(import_type=import_type)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status__in=status_filter.split(","))

        serializer = DocumentImportSerializer(qs[:50], many=True, context={"request": request})
        return Response(serializer.data)

    def post(self, request):
        """Create a new import and dispatch the Celery parse task."""
        ser = DocumentImportCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from components.shared_platform.application.providers.uploads_models_provider import get_uploads_models_provider

        File = get_uploads_models_provider().File
        from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider

        Workspace = get_workspaces_models_provider().Workspace

        workspace = get_object_or_404(Workspace, pk=data["workspace"])
        source_file = get_object_or_404(File, pk=data["source_file"])

        # Detect format from filename
        ext_map = {
            ".csv": "csv",
            ".pdf": "pdf",
            ".docx": "docx",
            ".doc": "doc",
            ".xlsx": "xlsx",
            ".xls": "xls",
            ".json": "json",
            ".txt": "txt",
        }
        filename = source_file.file.name or ""
        ext = os.path.splitext(filename)[1].lower()
        source_format = ext_map.get(ext, "unknown")

        doc_import = DocumentImport.objects.create(
            workspace=workspace,
            uploaded_by=request.user,
            source_file=source_file,
            original_filename=os.path.basename(filename),
            import_type=data["import_type"],
            source_format=source_format,
            use_ai=data["use_ai"],
            config=data.get("config", {}),
            status=DocumentImport.STATUS_QUEUED,
            queued_at=timezone.now(),
        )

        # Dispatch Celery task
        from components.shared_platform.application.providers.document_import_task_provider import (
            get_document_import_task_provider,
        )

        _doc_tasks = get_document_import_task_provider()
        _parse_delay = _doc_tasks.parse_delay_callable()

        # The DocumentImport row above is created inside DRF's per-request
        # transaction. Dispatching the task naked races the commit — a fast
        # worker can pick up the message and do .objects.get(pk=...) before
        # the row is visible to other DB connections, causing DoesNotExist.
        # transaction.on_commit defers dispatch until the transaction lands;
        # if it rolls back, the dispatch is silently dropped (which is what
        # we want). See celery-tasks skill rule 6.
        transaction.on_commit(lambda: _parse_delay(doc_import.pk))

        # Emit workflow event for document upload
        _doc_tasks.emit_event(
            doc_import,
            "document_uploaded",
            {
                "import_id": doc_import.pk,
                "import_type": doc_import.import_type,
                "filename": doc_import.original_filename,
            },
        )

        out = DocumentImportSerializer(doc_import, context={"request": request})
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


class DocumentImportDetailView(APIView):
    """Retrieve or update a single import."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-detail"

    def get(self, request, import_id):
        doc_import = get_object_or_404(DocumentImport, pk=import_id)
        serializer = DocumentImportSerializer(doc_import, context={"request": request})
        return Response(serializer.data)


class DocumentImportRowListView(APIView):
    """List rows for an import."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-row-list"

    def get(self, request, import_id):
        doc_import = get_object_or_404(DocumentImport, pk=import_id)
        rows = doc_import.rows.all()
        serializer = DocumentImportRowSerializer(rows, many=True)
        return Response(serializer.data)


class DocumentImportRowDetailView(APIView):
    """Update or delete a single row."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-row-detail"

    def patch(self, request, import_id, row_id):
        row = get_object_or_404(
            DocumentImportRow,
            pk=row_id,
            document_import_id=import_id,
        )
        serializer = DocumentImportRowSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(user_modified=True)
        return Response(serializer.data)

    def delete(self, request, import_id, row_id):
        row = get_object_or_404(
            DocumentImportRow,
            pk=row_id,
            document_import_id=import_id,
        )
        row.delete()

        # Refresh counts
        doc_import = get_object_or_404(DocumentImport, pk=import_id)
        doc_import.row_count = doc_import.rows.count()
        doc_import.valid_row_count = doc_import.rows.filter(is_valid=True).count()
        doc_import.save(update_fields=["row_count", "valid_row_count", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentImportRetryView(APIView):
    """Re-enqueue a failed or stuck import.

    The watchdog (``sweep_stuck_document_imports``) auto-retries silent
    deaths twice before marking an import ``failed``. This endpoint is
    the user-facing escape hatch for when they want to try again after
    the automatic attempts have been exhausted.
    """

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-retry"
    lookup_url_kwarg = "import_id"

    def post(self, request, import_id):
        doc_import = get_object_or_404(DocumentImport, pk=import_id)
        self.check_object_permissions(request, doc_import)

        if not doc_import.source_file_id:
            return Response(
                {"error": "Import has no source file attached; cannot retry."},
                status=400,
            )

        if doc_import.status not in (
            DocumentImport.STATUS_FAILED,
            DocumentImport.STATUS_PARSING,
            DocumentImport.STATUS_PENDING,
            DocumentImport.STATUS_QUEUED,
        ):
            return Response(
                {
                    "error": (
                        f"Import is '{doc_import.status}', cannot retry. Only failed or stuck imports are retryable."
                    )
                },
                status=400,
            )

        doc_import.status = DocumentImport.STATUS_PENDING
        doc_import.retry_count = (doc_import.retry_count or 0) + 1
        doc_import.error_message = ""
        doc_import.last_heartbeat_at = None
        doc_import.queued_at = timezone.now()
        doc_import.save(
            update_fields=[
                "status",
                "retry_count",
                "error_message",
                "last_heartbeat_at",
                "queued_at",
                "updated_at",
            ]
        )

        from components.shared_platform.application.providers.document_import_task_provider import (
            get_document_import_task_provider,
        )

        get_document_import_task_provider().parse_delay(doc_import.pk)

        return Response(
            DocumentImportSerializer(doc_import, context={"request": request}).data,
            status=status.HTTP_202_ACCEPTED,
        )


class DocumentImportApplyView(APIView):
    """Apply approved rows — creates actual records in the target context."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "document-import-apply"

    # Registry of applier functions per import_type.
    # Each applier receives (doc_import, rows, config) and returns a count.
    APPLIERS = {}

    @classmethod
    def register_applier(cls, import_type: str, fn):
        cls.APPLIERS[import_type] = fn

    def post(self, request, import_id):
        doc_import = get_object_or_404(DocumentImport, pk=import_id)

        if doc_import.status not in (
            DocumentImport.STATUS_READY,
            DocumentImport.STATUS_NEEDS_REVIEW,
        ):
            return Response(
                {"error": f"Import is '{doc_import.status}', cannot apply."},
                status=400,
            )

        skip_invalid = request.data.get("skip_invalid", "true") not in ("false", False)
        create_categories = request.data.get("create_missing_categories", "true") not in ("false", False)

        rows = doc_import.rows.all()
        if skip_invalid:
            rows = rows.filter(is_valid=True)

        applier = self.APPLIERS.get(doc_import.import_type)
        if not applier:
            # No applier registered for this import_type. Appliers are
            # registered per bounded context via ``register_applier`` —
            # the shared pipeline itself is context-agnostic.
            return Response(
                {"error": f"No applier registered for import_type '{doc_import.import_type}'."},
                status=400,
            )

        try:
            applied_count = applier(
                doc_import=doc_import,
                rows=list(rows),
                user=request.user,
                create_missing_categories=create_categories,
            )
        except Exception as exc:
            logger.exception("Import apply failed: %s", exc)
            return Response({"error": str(exc)[:300]}, status=500)

        doc_import.status = DocumentImport.STATUS_APPLIED
        doc_import.applied_row_count = applied_count
        doc_import.applied_at = timezone.now()
        doc_import.save(
            update_fields=[
                "status",
                "applied_row_count",
                "applied_at",
                "updated_at",
            ]
        )

        # Mark rows as applied — but ONLY rows the applier actually
        # persisted. Rows the applier explicitly skipped keep their
        # SKIPPED status so the preview UI doesn't show 'Applied' for
        # rows that produced nothing.
        doc_import.rows.filter(
            is_valid=True,
        ).exclude(
            status=DocumentImportRow.ROW_STATUS_SKIPPED,
        ).update(status=DocumentImportRow.ROW_STATUS_APPLIED)

        # Emit workflow event
        from components.shared_platform.application.providers.document_import_task_provider import (
            get_document_import_task_provider,
        )

        get_document_import_task_provider().emit_event(
            doc_import,
            "document_applied",
            {
                "import_id": doc_import.pk,
                "import_type": doc_import.import_type,
                "applied_count": applied_count,
                "filename": doc_import.original_filename,
            },
        )

        out = DocumentImportSerializer(doc_import, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)

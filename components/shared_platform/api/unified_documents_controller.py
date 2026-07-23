"""Unified documents API — single view of all documents across the platform.

Merges files from every upload source (AI chat, expense import, budget import,
income import, knowledge base, manual upload) into one paginated list.
"""

from __future__ import annotations

import logging

from rest_framework import serializers as drf_serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from components.shared_platform.application.providers.uploads_models_provider import get_uploads_models_provider
from components.workspace.api.permissions import IsOrgOwnerOrMember

File = get_uploads_models_provider().File

logger = logging.getLogger(__name__)


class UnifiedDocumentSerializer(drf_serializers.ModelSerializer):
    filename = drf_serializers.SerializerMethodField()
    file_url = drf_serializers.SerializerMethodField()
    owner_name = drf_serializers.SerializerMethodField()
    import_info = drf_serializers.SerializerMethodField()
    workflow_runs = drf_serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = [
            "id",
            "filename",
            "file_url",
            "file_type",
            "source",
            "processing_status",
            "ai_insights",
            "owner",
            "owner_name",
            "workspace_id",
            "pdf_page_count",
            "created",
            "processed_at",
            "import_info",
            "workflow_runs",
        ]

    def get_filename(self, obj):
        name = obj.file.name if obj.file else ""
        # Strip the upload path prefix, return just the filename
        return name.rsplit("/", 1)[-1] if name else ""

    def get_file_url(self, obj):
        request = self.context.get("request")
        return obj.get_absolute_file_url(request=request)

    def get_owner_name(self, obj):
        if not obj.owner:
            return ""
        return obj.owner.get_full_name() or getattr(obj.owner, "username", "") or str(obj.owner)

    def get_import_info(self, obj):
        """Return info from the linked DocumentImport if one exists."""
        cache = self.context.get("_import_cache")
        if cache is None:
            return None
        imp = cache.get(obj.pk)
        if not imp:
            return None
        return {
            "import_id": imp.pk,
            "import_type": imp.import_type,
            "status": imp.status,
            "row_count": imp.row_count,
            "valid_row_count": imp.valid_row_count,
            "applied_row_count": imp.applied_row_count,
        }

    def get_workflow_runs(self, obj):
        """Return any workflow runs triggered by this document."""
        cache = self.context.get("_workflow_run_cache")
        if cache is None:
            return []
        return cache.get(obj.pk, [])


class UnifiedDocumentListView(APIView):
    """List all documents for a workspace, regardless of upload source."""

    permission_classes = (IsOrgOwnerOrMember,)
    name = "unified-document-list"

    def get(self, request):
        workspace_id = request.query_params.get("workspace")
        if not workspace_id:
            return Response({"error": "workspace query param required"}, status=400)

        source_filter = request.query_params.get("source")
        file_type_filter = request.query_params.get("file_type")

        qs = File.objects.filter(workspace_id=workspace_id).select_related("owner").order_by("-created")

        if source_filter:
            qs = qs.filter(source__in=source_filter.split(","))
        if file_type_filter:
            qs = qs.filter(file_type__in=file_type_filter.split(","))

        # Limit to reasonable page size
        limit = min(int(request.query_params.get("limit", 100)), 200)
        files = list(qs[:limit])
        file_ids = [f.pk for f in files]

        # Batch-load related DocumentImport records
        import_cache = {}
        try:
            from components.shared_platform.application.providers.imports_models_provider import (
                get_imports_models_provider,
            )

            DocumentImport = get_imports_models_provider().DocumentImport

            imports = DocumentImport.objects.filter(source_file_id__in=file_ids).order_by("-created_at")
            for imp in imports:
                if imp.source_file_id not in import_cache:
                    import_cache[imp.source_file_id] = imp
        except Exception:
            pass

        # Batch-load workflow runs linked to these documents
        workflow_run_cache = {}
        try:
            from components.workspace.application.providers.workspaces_models_provider import (
                get_workspaces_models_provider,
            )

            WorkflowRun = get_workspaces_models_provider().WorkflowRun

            import_ids = [imp.pk for imp in import_cache.values()]
            if import_ids:
                runs = (
                    WorkflowRun.objects.filter(
                        trigger_type__startswith="document_",
                    )
                    .select_related("workflow")
                    .order_by("-started_at")[:200]
                )

                for run in runs:
                    payload = run.trigger_payload or {}
                    imp_id = payload.get("import_id")
                    if not imp_id:
                        continue
                    # Find the file_id for this import
                    for fid, imp in import_cache.items():
                        if imp.pk == imp_id:
                            if fid not in workflow_run_cache:
                                workflow_run_cache[fid] = []
                            workflow_run_cache[fid].append(
                                {
                                    "run_id": str(run.pk),
                                    "workflow_id": str(run.workflow_id),
                                    "workflow_name": getattr(run.workflow, "name", ""),
                                    "status": run.status,
                                    "trigger_type": run.trigger_type,
                                    "started_at": run.started_at.isoformat() if run.started_at else None,
                                }
                            )
                            break
        except Exception:
            pass

        context = {
            "request": request,
            "_import_cache": import_cache,
            "_workflow_run_cache": workflow_run_cache,
        }

        serializer = UnifiedDocumentSerializer(files, many=True, context=context)
        rows = list(serializer.data)

        # Fold in generated report PDFs as documents (a report with a rendered
        # PDF is a file in this workspace too). Guarded like the other cross-
        # context blocks so a report-context hiccup never breaks the library.
        # Honours the source filter: only include when unfiltered or "report"
        # is one of the requested sources.
        if not source_filter or "report" in source_filter.split(","):
            try:
                from components.report.application.providers.report_documents_provider import (
                    get_report_documents_reader,
                )

                rows.extend(get_report_documents_reader().list_documents(workspace_id, request=request))
            except Exception:
                logger.exception("unified_documents report fold-in failed workspace_id=%s", workspace_id)

        # Sort merged list by ``created`` desc so uploads interleave
        # chronologically. Falls back to empty string when ``created``
        # is missing (shouldn't happen but we're defensive).
        rows.sort(key=lambda r: r.get("created") or "", reverse=True)
        return Response(rows)

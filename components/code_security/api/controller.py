"""Code-security REST surface — the on-demand repo-scan trigger + snapshots (ADR 0019).

Thin controllers: authorize → call the use case → respond. The scan runs as the
``scanning.run_scan`` Celery task (async, isolated, retryable) on the
``code_security`` queue, which renders an ephemeral Opengrep Job via the
ScanExecutionBackend and emits FindingObserved → the findings SSOT. RBAC mirrors
the Trivy scan-now endpoint exactly (workspace member + the pillar's feature
flag); the repo-allowlist consent gate is enforced by the use case (trigger time)
AND the vend seam (scan time, fail closed).
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

_SOURCE = "code_security.opengrep"
_FLAG = "feature.code_security"


def _is_workspace_member(user, workspace_id) -> bool:
    from components.shared_platform.application.providers.workspace_access_provider import (
        get_workspace_access_adapter,
    )

    return (
        getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
        or str(workspace_id) in get_workspace_access_adapter().accessible_workspace_ids(user_id=user.id)
    )


def _gate(request, workspace_id) -> Response | None:
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )

    if not _is_workspace_member(request.user, workspace_id):
        return Response({"success": False, "error": "forbidden"}, status=403)
    if not get_feature_flags_provider().is_feature_enabled(_FLAG, workspace_id=workspace_id):
        return Response({"success": False, "error": "feature_disabled"}, status=403)
    return None


class RepoScanView(APIView):
    """POST /code-security/workspaces/<ws>/scan/ — kick off an Opengrep repo scan."""

    name = "code-security-scan"
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, workspace_id):
        from components.code_security.api.requests.scan_request import RepoScanRequest
        from components.code_security.api.resources.scan_resource import RepoScanResource
        from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
            RepoScanRejected,
            TriggerRepoScanUseCase,
        )

        denied = _gate(request, workspace_id)
        if denied is not None:
            return denied

        req = RepoScanRequest.from_data(request.data)
        try:
            dispatched = TriggerRepoScanUseCase().execute(
                workspace_id=workspace_id,
                repo=req.repo,
                connection_id=req.connection_id,
                triggered_by=request.user.id,  # provenance: who pressed SCAN
            )
        except RepoScanRejected as exc:
            # Budget rejections are 429 (retriable, with Retry-After); consent
            # failures stay 4xx.
            if exc.code in ("scan_cooldown", "scan_already_running"):
                body = {"success": False, "error": exc.code, "detail": str(exc)}
                if exc.retry_after is not None:
                    body["retry_after"] = exc.retry_after
                response = Response(body, status=429)
                if exc.retry_after is not None:
                    response["Retry-After"] = str(exc.retry_after)
                return response
            status = 400 if exc.code == "invalid_repo" else 403
            return Response({"success": False, "error": exc.code, "detail": str(exc)}, status=status)

        resource = RepoScanResource(task_id=dispatched["task_id"], repo=dispatched["repo"], source=_SOURCE)
        return Response({"success": True, "data": resource.to_dict()}, status=202)


class RepoScanStatusListView(APIView):
    """GET /code-security/workspaces/<ws>/repos/ — the CODE REPOS card's read.

    Every scannable (allowlisted) repo with its scan provenance: last-scanned
    timestamp + status + duration + who/what triggered it, whether a scan is in
    flight, and the remaining anti-spam cooldown so the UI can disable SCAN with
    a countdown instead of bouncing off the server gate.
    """

    name = "code-security-repos"
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        from components.code_security.application.use_cases.list_repo_scan_status_use_case import (
            ListRepoScanStatusUseCase,
        )
        from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
            COOLDOWN_SECONDS,
        )

        denied = _gate(request, workspace_id)
        if denied is not None:
            return denied

        rows = ListRepoScanStatusUseCase().execute(workspace_id=workspace_id, cooldown_seconds=COOLDOWN_SECONDS)
        return Response({"success": True, "data": rows, "cooldown_seconds": COOLDOWN_SECONDS})


class RepoScanSnapshotListView(APIView):
    """GET /code-security/workspaces/<ws>/snapshots/ — recent per-repo scan snapshots.

    The HUD tile's read: severity counts per completed scan, newest first
    (optionally filtered with ``?repo=owner/repo``). A thin own-context read —
    pagination-by-cap (the tile shows the recent window, not an archive).
    """

    name = "code-security-snapshots"
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, workspace_id):
        from components.code_security.api.resources.scan_resource import RepoScanSnapshotResource
        from components.code_security.application.providers.snapshot_provider import (
            list_recent_snapshots,
        )

        denied = _gate(request, workspace_id)
        if denied is not None:
            return denied

        repo = (request.query_params.get("repo") or "").strip()
        rows = [
            RepoScanSnapshotResource.from_model(row).to_dict() for row in list_recent_snapshots(workspace_id, repo=repo)
        ]
        return Response({"success": True, "data": rows})

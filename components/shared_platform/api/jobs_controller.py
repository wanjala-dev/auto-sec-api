"""Read API for background jobs — the generic long-running-task progress surface.

Thin controllers: membership gate → read service → JSON. No ORM/business logic
here (lives in ``infrastructure/services/job_queries.py``). Any workspace member
can read their jobs; the HUD polls ``.../active/`` to render live progress rings
and reads a single job for a per-resource WebSocket subscription's initial state.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView


class ActiveJobsView(APIView):
    """GET /jobs/workspaces/<ws>/active/?type=<job_type> — running jobs."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "jobs-active"

    def get(self, request, workspace_id):
        from components.shared_platform.infrastructure.services.job_queries import (
            is_workspace_member,
            list_active_jobs,
        )

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        jobs = list_active_jobs(
            workspace_id=workspace_id,
            job_type=request.query_params.get("type") or None,
        )
        return Response({"success": True, "data": jobs})


class JobDetailView(APIView):
    """GET /jobs/workspaces/<ws>/<job_id>/ — a single job snapshot."""

    permission_classes = (permissions.IsAuthenticated,)
    name = "jobs-detail"

    def get(self, request, workspace_id, job_id):
        from components.shared_platform.infrastructure.services.job_queries import (
            get_job_for_workspace,
            is_workspace_member,
        )

        if not is_workspace_member(user=request.user, workspace_id=workspace_id):
            return Response({"success": False, "error": "forbidden"}, status=403)
        job = get_job_for_workspace(workspace_id=workspace_id, job_id=job_id)
        if job is None:
            return Response({"success": False, "error": "not_found"}, status=404)
        return Response({"success": True, "data": job})

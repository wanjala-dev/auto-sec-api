"""Views for workflow definitions, bindings, and executions."""

from __future__ import annotations

from typing import Any, Dict, Optional

from django.utils import timezone

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle

from components.shared_platform.api.permissions import RequiresFeatureFlag
from components.workspace.api.permissions import IsOrgOwnerOrMember, IsWorkspaceAdmin


# End-user workflow UI (templates, workflows, bindings, runs, triggers) is
# gated behind feature.workflows_ui per the GTM scope freeze. The workflow
# engine + Celery task runner + dispatcher (emit_workflow_event) stay on
# internally — only the UI-facing controllers require the flag. See
# docs/plans/GTM_SCOPE_FREEZE_CHECKLIST.md entry 4.
_WORKFLOWS_UI_FLAG_KEY = "feature.workflows_ui"
from components.workspace.application.providers.workspaces_models_provider import get_workspaces_models_provider
_wsp_workflows = get_workspaces_models_provider()
Workflow = _wsp_workflows.Workflow
WorkflowBinding = _wsp_workflows.WorkflowBinding
WorkflowRun = _wsp_workflows.WorkflowRun
from components.workflow.domain.constants import TRIGGER_CATALOG
from components.workflow.api.errors import WorkflowExceptionHandlerMixin
from components.workflow.mappers.rest.workflow_serializers import (
    WorkflowBindingSerializer,
    WorkflowEnrollmentSerializer,
    WorkflowGraphValidateSerializer,
    WorkflowRunCreateSerializer,
    WorkflowRunSerializer,
    WorkflowScheduleSerializer,
    WorkflowStepEventSerializer,
    WorkflowSummarySerializer,
    WorkflowTemplateSerializer,
    WorkflowSerializer,
)
from components.workflow.application.providers.workflow_tasks_provider import (
    get_workflow_tasks_provider,
)
from components.workflow.application.service import WorkflowService


WORKSPACE_KEYS = ("workspace_id", "workspace", "workspaceId", "workspace_pk")

# Module-level service singleton
_service = None


def get_service() -> WorkflowService:
    """Get or create the WorkflowService singleton."""
    global _service
    if _service is None:
        _service = WorkflowService()
    return _service


def resolve_workspace_id(request) -> Optional[str]:
    """Resolve a workspace id from request data, query params, or user profile."""

    parser_context = getattr(request, "parser_context", None) or {}
    kwargs = parser_context.get("kwargs") or {}
    for key in WORKSPACE_KEYS:
        value = kwargs.get(key)
        if value:
            return value

    for key in WORKSPACE_KEYS:
        value = getattr(request, "query_params", {}).get(key)
        if value:
            return value

    data = getattr(request, "data", {}) or {}
    for key in WORKSPACE_KEYS:
        value = data.get(key)
        if value:
            return value

    profile = getattr(getattr(request, "user", None), "profile", None)
    if profile and getattr(profile, "active_workspace_id", None):
        return str(profile.active_workspace_id)

    return None


class WorkflowTemplateViewSet(WorkflowExceptionHandlerMixin, viewsets.ModelViewSet):
    """CRUD for workflow templates — system (staff) and workspace (user)."""

    serializer_class = WorkflowTemplateSerializer
    permission_classes = (IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _WORKFLOWS_UI_FLAG_KEY
    lookup_field = "id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    # The template catalog is a small, curated reference set (system templates +
    # a workspace's own) that feeds the builder's template PICKER — the picker
    # must show every template, so a paginated response silently truncates the
    # gallery. With PAGE_SIZE=10 and 12+ system templates, ``sponsor`` landed on
    # page 2 and never reached the client, which then fell back to a stale local
    # stub graph that failed Publish. Like feature flags / currencies, this is
    # bounded reference data returned in full, not an unbounded list — pagination
    # is disabled here on purpose (see .claude/rules/performance.md §8).
    pagination_class = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = get_service()

    def get_queryset(self):
        scope = self.request.query_params.get("scope")
        workspace_id = resolve_workspace_id(self.request)
        return self.service.get_templates(
            scope=scope, workspace_id=workspace_id, user=self.request.user
        )

    def get_permissions(self):
        if self.action in {"create", "partial_update", "destroy"}:
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        return [permissions.IsAuthenticated(), IsOrgOwnerOrMember()]

    def create(self, request, *args, **kwargs):
        serializer = WorkflowTemplateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        # Staff can create system templates
        if request.user.is_staff and request.data.get("is_system"):
            template = serializer.save(created_by=request.user, is_system=True, workspace=None)
        else:
            template = serializer.save(created_by=request.user)
        return Response(WorkflowTemplateSerializer(template).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only staff can edit system templates
        if instance.is_system and not request.user.is_staff:
            return Response(
                {"detail": "System templates can only be edited by staff."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = WorkflowTemplateSerializer(
            instance, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(WorkflowTemplateSerializer(instance).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_system and not request.user.is_staff:
            return Response(
                {"detail": "System templates cannot be deleted."},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkflowViewSet(WorkflowExceptionHandlerMixin, viewsets.ModelViewSet):
    """Manage workflows, publish versions, and run actions."""

    permission_classes = (permissions.IsAuthenticated, IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _WORKFLOWS_UI_FLAG_KEY
    lookup_field = "id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = get_service()

    def get_permissions(self):
        """Allow org members to read, but require workspace admins for mutations."""

        admin_actions = {
            "create",
            "update",
            "partial_update",
            "destroy",
            "publish",
            "archive",
            "clone",
            "enroll",
            "unenroll",
        }
        if self.action in admin_actions:
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        if self.action == "runs" and self.request.method.lower() == "post":
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        # Schedule writes (create / update / delete) require an admin; reads
        # (GET list) are open to org members like the other read endpoints.
        if (
            self.action in {"schedules", "schedule_detail"}
            and self.request.method.lower() in {"post", "patch", "put", "delete"}
        ):
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        return [permissions.IsAuthenticated(), IsOrgOwnerOrMember()]

    def get_queryset(self):
        workspace_id = resolve_workspace_id(self.request)
        status_value = self.request.query_params.get("status")
        goal = self.request.query_params.get("goal")
        template_id = self.request.query_params.get("template_id")
        scheduled_param = self.request.query_params.get("scheduled")
        scheduled = (
            str(scheduled_param).lower() in ("1", "true", "yes")
            if scheduled_param is not None
            else None
        )

        queryset = self.service.get_workflows(
            workspace_id=workspace_id,
            status=status_value,
            goal=goal,
            template_id=template_id,
            scheduled=scheduled,
            exclude_deleted=True,
        )

        if getattr(self, "action", None) == "list":
            queryset = queryset.defer("graph")
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return WorkflowSummarySerializer
        return WorkflowSerializer

    def get_throttles(self):
        if self.action == "runs" and self.request.method == "POST":
            self.throttle_scope = "workflow_runs"
            return [
                ScopedRateThrottle(),
                UserRateThrottle(),
                AnonRateThrottle(),
            ]
        return super().get_throttles()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        workflow = self.get_object()
        self.service.soft_delete_workflow(workflow)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="validate")
    def validate_graph(self, request):
        serializer = WorkflowGraphValidateSerializer(data=request.data)
        if serializer.is_valid():
            return Response({"valid": True, "errors": []})
        return Response({"valid": False, "errors": serializer.errors.get("graph", serializer.errors)}, status=400)

    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, id=None):
        workflow = self.get_object()
        notes = request.data.get("notes", "")
        workflow = self.service.publish_workflow(
            workflow,
            notes=notes,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response({"id": str(workflow.id), "status": workflow.status, "version": workflow.version})

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, id=None):
        workflow = self.get_object()
        workflow = self.service.archive_workflow(workflow)
        serializer = WorkflowSerializer(workflow, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="clone")
    def clone(self, request, id=None):
        workflow = self.get_object()
        clone = self.service.clone_workflow(
            workflow,
            created_by=request.user if request.user.is_authenticated else None,
        )
        serializer = WorkflowSerializer(clone, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="runs")
    def runs(self, request, id=None):
        workflow = self.get_object()

        if request.method.lower() == "get":
            runs = self.service.get_runs(workflow_id=str(workflow.id))
            status_filter = request.query_params.get("status")
            if status_filter:
                runs = runs.filter(status=status_filter)
            page = self.paginate_queryset(runs)
            serializer = WorkflowRunSerializer(page or runs, many=True)
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        serializer = WorkflowRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        idempotency_key = payload.get("idempotency_key") or ""

        run_ids = self.service.create_runs_with_idempotency(
            workflow=workflow,
            targets=payload["targets"],
            trigger_type=payload["trigger_type"],
            trigger_payload=payload.get("trigger_payload"),
            idempotency_key=idempotency_key,
        )

        # Enqueue task for each new run
        for run_id in run_ids:
            get_workflow_tasks_provider().enqueue_run_start(run_id)

        return Response({"queued": True, "run_ids": run_ids}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="enroll")
    def enroll(self, request, id=None):
        workflow = self.get_object()
        targets = request.data.get("targets") or []
        # Validate each target's shape before touching the engine.
        for target in targets:
            serializer = WorkflowEnrollmentSerializer(
                data={
                    "workflow_id": str(workflow.id),
                    "target_type": target.get("target_type"),
                    "target_id": target.get("target_id"),
                }
            )
            serializer.is_valid(raise_exception=True)

        # Enroll AND start a run for each target (manual enrollment skips the
        # trigger and begins at the start node).
        result = self.service.enroll_targets(
            workflow=workflow,
            targets=targets,
            idempotency_key=request.data.get("idempotency_key"),
        )
        for run_id in result["run_ids"]:
            get_workflow_tasks_provider().enqueue_run_start(run_id)

        response = WorkflowEnrollmentSerializer(result["enrollments"], many=True).data
        return Response(
            {
                "created": len(result["enrollments"]),
                "enrollments": response,
                "run_ids": result["run_ids"],
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="enrollments")
    def enrollments(self, request, id=None):
        workflow = self.get_object()
        enrollments = self.service.get_enrollments(workflow_id=str(workflow.id))
        status_filter = request.query_params.get("status")
        target_type = request.query_params.get("target_type")
        if status_filter:
            enrollments = enrollments.filter(status=status_filter)
        if target_type:
            enrollments = enrollments.filter(target_type=target_type)

        page = self.paginate_queryset(enrollments)
        serializer = WorkflowEnrollmentSerializer(page or enrollments, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="unenroll")
    def unenroll(self, request, id=None):
        workflow = self.get_object()
        targets = request.data.get("targets") or []
        removed = self.service.delete_enrollments(str(workflow.id), targets)
        return Response({"removed": removed})

    @action(detail=True, methods=["get", "post"], url_path="schedules")
    def schedules(self, request, id=None):
        """List a workflow's recurring schedules, or create one."""
        workflow = self.get_object()
        if request.method.lower() == "get":
            schedules = self.service.list_schedules(str(workflow.id))
            page = self.paginate_queryset(schedules)
            serializer = WorkflowScheduleSerializer(page or schedules, many=True)
            if page is not None:
                return self.get_paginated_response(serializer.data)
            return Response(serializer.data)

        serializer = WorkflowScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = self.service.create_schedule(
            workflow=workflow,
            now=timezone.now(),
            created_by=request.user,
            **serializer.validated_data,
        )
        return Response(
            WorkflowScheduleSerializer(schedule).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"schedules/(?P<schedule_id>[^/.]+)",
    )
    def schedule_detail(self, request, id=None, schedule_id=None):
        """Update or delete a single schedule belonging to this workflow."""
        workflow = self.get_object()
        schedule = self.service.get_schedule(schedule_id)
        if schedule is None or str(schedule.workflow_id) != str(workflow.id):
            raise NotFound("Schedule not found.")

        if request.method.lower() == "delete":
            self.service.delete_schedule(schedule_id)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = WorkflowScheduleSerializer(
            schedule, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = self.service.update_schedule(
            schedule, timezone.now(), **serializer.validated_data
        )
        return Response(WorkflowScheduleSerializer(updated).data)


class WorkflowBindingViewSet(WorkflowExceptionHandlerMixin, viewsets.ModelViewSet):
    """Create or remove workflow bindings to feature events."""

    serializer_class = WorkflowBindingSerializer
    permission_classes = (permissions.IsAuthenticated, IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _WORKFLOWS_UI_FLAG_KEY
    lookup_field = "id"
    http_method_names = ["get", "post", "delete", "head", "options"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = get_service()

    def get_permissions(self):
        if self.request.method.lower() in {"post", "delete"}:
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        return [permissions.IsAuthenticated(), IsOrgOwnerOrMember()]

    def get_queryset(self):
        workflow_id = self.request.query_params.get("workflow_id")
        source_type = self.request.query_params.get("source_type")
        source_id = self.request.query_params.get("source_id")
        workspace_id = resolve_workspace_id(self.request)
        return self.service.get_bindings(
            workflow_id=workflow_id,
            source_type=source_type,
            source_id=source_id,
            workspace_id=workspace_id,
        )


class WorkflowRunViewSet(viewsets.ReadOnlyModelViewSet):
    """Run detail and execution actions."""

    serializer_class = WorkflowRunSerializer
    permission_classes = (permissions.IsAuthenticated, IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _WORKFLOWS_UI_FLAG_KEY
    lookup_field = "id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = get_service()

    def get_queryset(self):
        return self.service.get_runs().select_related("workflow")

    def get_permissions(self):
        admin_actions = {"cancel", "retry", "pause", "resume", "complete_step", "input_step"}
        if self.action in admin_actions:
            return [permissions.IsAuthenticated(), IsWorkspaceAdmin()]
        return [permissions.IsAuthenticated(), IsOrgOwnerOrMember()]

    def list(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def get_throttles(self):
        if self.action in {"complete_step", "input_step"}:
            self.throttle_scope = "workflow_steps"
            return [
                ScopedRateThrottle(),
                UserRateThrottle(),
                AnonRateThrottle(),
            ]
        if self.action in {"cancel", "retry", "pause", "resume"}:
            self.throttle_scope = "workflow_runs"
            return [
                ScopedRateThrottle(),
                UserRateThrottle(),
                AnonRateThrottle(),
            ]
        return super().get_throttles()

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, id=None):
        run = self.get_object()
        run = self.service.cancel_run(run)
        return Response(WorkflowRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, id=None):
        run = self.get_object()
        run = self.service.retry_run(run)
        # Resume at the failed node (retry_run points current_node_id there);
        # only fall back to a full restart if there's no resume point.
        if run.current_node_id:
            get_workflow_tasks_provider().enqueue_run_step(
                str(run.id), run.current_node_id
            )
        else:
            get_workflow_tasks_provider().enqueue_run_start(str(run.id))
        return Response(WorkflowRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request, id=None):
        run = self.get_object()
        run = self.service.pause_run(run)
        return Response(WorkflowRunSerializer(run).data)

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, id=None):
        run = self.get_object()
        run = self.service.resume_run(run)
        if run.current_node_id:
            get_workflow_tasks_provider().enqueue_run_step(str(run.id), run.current_node_id)
        else:
            get_workflow_tasks_provider().enqueue_run_start(str(run.id))
        return Response(WorkflowRunSerializer(run).data)

    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, id=None):
        run = self.get_object()
        events = self.service.get_step_events(run)
        page = self.paginate_queryset(events)
        serializer = WorkflowStepEventSerializer(page or events, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path=r"steps/(?P<node_id>[^/.]+)/complete")
    def complete_step(self, request, id=None, node_id=None):
        run = self.get_object()
        output = request.data.get("output") or {}
        if not self.service.node_exists_in_graph(run, node_id):
            raise NotFound("Node does not exist in workflow graph.")
        self.service.complete_step(run, node_id, output, event_type="completed")

        # Handle task enqueueing based on graph navigation
        graph = run.workflow.graph or {}
        nodes = {node.get("id"): node for node in graph.get("nodes", []) if isinstance(node, dict)}
        node = nodes.get(node_id)

        if node and node.get("type") == "decision":
            get_workflow_tasks_provider().enqueue_run_branch(str(run.id), node_id, output)
        elif run.current_node_id:
            get_workflow_tasks_provider().enqueue_run_step(str(run.id), run.current_node_id)
        else:
            get_workflow_tasks_provider().enqueue_run_complete(str(run.id))

        return Response({"status": "ok", "run_id": str(run.id), "current_node_id": run.current_node_id})

    @action(detail=True, methods=["post"], url_path=r"steps/(?P<node_id>[^/.]+)/input")
    def input_step(self, request, id=None, node_id=None):
        run = self.get_object()
        output = request.data.get("input") or {}
        if not self.service.node_exists_in_graph(run, node_id):
            raise NotFound("Node does not exist in workflow graph.")
        self.service.complete_step(run, node_id, output, event_type="completed")

        # Handle task enqueueing based on graph navigation
        graph = run.workflow.graph or {}
        nodes = {node.get("id"): node for node in graph.get("nodes", []) if isinstance(node, dict)}
        node = nodes.get(node_id)

        if node and node.get("type") == "decision":
            get_workflow_tasks_provider().enqueue_run_branch(str(run.id), node_id, output)
        elif run.current_node_id:
            get_workflow_tasks_provider().enqueue_run_step(str(run.id), run.current_node_id)
        else:
            get_workflow_tasks_provider().enqueue_run_complete(str(run.id))

        return Response({"status": "ok", "run_id": str(run.id), "current_node_id": run.current_node_id})


class WorkflowTriggerList(WorkflowExceptionHandlerMixin, APIView):
    """Return the static trigger catalog for workflow bindings."""

    permission_classes = (permissions.IsAuthenticated, IsOrgOwnerOrMember, RequiresFeatureFlag)
    feature_flag_key = _WORKFLOWS_UI_FLAG_KEY

    def get(self, request):
        goal = (request.query_params.get("goal") or "").strip().lower()
        results = []
        for trigger in TRIGGER_CATALOG:
            if goal and trigger.goal_ids and goal not in trigger.goal_ids:
                continue
            results.append(
                {
                    "id": trigger.id,
                    "label": trigger.label,
                    "source_type": trigger.source_type,
                    "goal_ids": list(trigger.goal_ids),
                    "compatible_node_types": list(trigger.compatible_node_types),
                }
            )
        return Response({"results": results})

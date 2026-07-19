"""Application service for the workflow bounded context.

Orchestrates workflow operations by delegating to the repository layer.
Handles business logic coordination with persistence.

Note: type annotations use ``Any`` for ORM model types so the
application layer stays free of infrastructure imports.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkflowService:
    """Application service for workflow operations.

    Coordinates business logic across repository layer and task scheduling.
    """

    def __init__(self):
        """Initialize service with repository."""
        from components.workflow.infrastructure.repositories.workflow_repository import (
            WorkflowRepository,
        )
        self.repo = WorkflowRepository()

    # ========================
    # Template Operations
    # ========================

    def get_templates(
        self,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
        user: Optional[Any] = None,
    ) -> "QuerySet":
        """Retrieve templates by scope, workspace, and user visibility."""
        return self.repo.get_templates(scope=scope, workspace_id=workspace_id, user=user)

    def get_template_by_id(self, template_id: str) -> Optional[Any]:
        """Retrieve a single template."""
        return self.repo.get_template_by_id(template_id)

    def create_template(
        self,
        id: str,
        label: str,
        description: str = "",
        category: str = "",
        version: str = "1",
        is_system: bool = False,
        default_graph: Dict[str, Any] = None,
        workspace_id: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> Any:
        """Create a new workflow template."""
        return self.repo.create_template(
            id=id,
            label=label,
            description=description,
            category=category,
            version=version,
            is_system=is_system,
            default_graph=default_graph,
            workspace_id=workspace_id,
            created_by=created_by,
        )

    # ========================
    # Workflow Operations
    # ========================

    def get_workflows(
        self,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        template_id: Optional[str] = None,
        scheduled: Optional[bool] = None,
        exclude_deleted: bool = True,
    ) -> "QuerySet":
        """Retrieve workflows with optional filters."""
        return self.repo.get_workflows(
            workspace_id=workspace_id,
            status=status,
            goal=goal,
            template_id=template_id,
            scheduled=scheduled,
            exclude_deleted=exclude_deleted,
        )

    def get_workflow_by_id(self, workflow_id: str) -> Optional[Any]:
        """Retrieve a single workflow."""
        return self.repo.get_workflow_by_id(workflow_id)

    def create_workflow(
        self,
        workspace_id: str,
        name: str,
        description: str = "",
        goal: str = "",
        template_id: Optional[str] = None,
        is_custom: bool = False,
        status: str = "draft",
        version: int = 1,
        graph: Dict[str, Any] = None,
        created_by: Optional[Any] = None,
    ) -> Any:
        """Create a new workflow."""
        return self.repo.create_workflow(
            workspace_id=workspace_id,
            name=name,
            description=description,
            goal=goal,
            template_id=template_id,
            is_custom=is_custom,
            status=status,
            version=version,
            graph=graph,
            created_by=created_by,
        )

    def update_workflow(
        self,
        workflow: Any,
        **kwargs
    ) -> Any:
        """Update a workflow with the given fields."""
        return self.repo.update_workflow(workflow, **kwargs)

    def publish_workflow(
        self,
        workflow: Any,
        notes: str = "",
        created_by: Optional[Any] = None,
    ) -> Any:
        """Publish a workflow version.

        Publish is the validation gate: drafts may be saved with an incomplete
        graph, but a workflow can only be PUBLISHED (and thus run) once its graph
        passes full structural + per-node validation. This is what keeps the
        engine from ever executing a half-configured graph.
        """
        from components.workflow.domain.validators import validate_graph
        from components.workflow.domain.errors import WorkflowGraphValidationError

        errors = validate_graph(getattr(workflow, "graph", None) or {})
        if errors:
            summary = "; ".join(
                f"{e.get('path', 'graph')}: {e.get('message', 'invalid')}" for e in errors[:5]
            )
            raise WorkflowGraphValidationError(
                f"Workflow graph is not valid for publishing — {summary}"
            )
        published = self.repo.publish_workflow(workflow, notes=notes, created_by=created_by)
        # Wire up the start node's trigger(s). A single start node may carry
        # multiple triggers ("group multiple triggers into one workflow") via
        # config.triggerTypes; we reconcile one binding per trigger so the
        # dispatcher routes every selected event to this workflow.
        self._sync_start_node_bindings(workflow)
        return published

    @staticmethod
    def _start_node_triggers(graph: Dict[str, Any]) -> List[tuple]:
        """Extract (source_type, trigger_type) pairs from the start node.

        Accepts ``config.triggerTypes`` (list) and/or ``config.triggerType``
        (single). Trigger ids are mapped to their source_type via TRIGGER_CATALOG;
        unknown trigger ids are skipped.
        """
        from components.workflow.domain.constants import TRIGGER_CATALOG

        source_by_trigger = {t.id: t.source_type for t in TRIGGER_CATALOG}
        nodes = (graph or {}).get("nodes") or []
        start = next(
            (n for n in nodes if isinstance(n, dict) and n.get("type") == "start"),
            None,
        )
        if not start:
            return []
        config = start.get("config") or {}
        ids: List[str] = []
        for value in config.get("triggerTypes") or []:
            if value and value not in ids:
                ids.append(str(value))
        single = config.get("triggerType")
        if single and single not in ids:
            ids.append(str(single))
        return [(source_by_trigger[i], i) for i in ids if i in source_by_trigger]

    def _sync_start_node_bindings(self, workflow: Any) -> None:
        triggers = self._start_node_triggers(getattr(workflow, "graph", None) or {})
        sync = getattr(self.repo, "sync_workflow_bindings", None)
        if sync is None:
            return
        sync(workflow_id=workflow.id, triggers=triggers)

    def archive_workflow(self, workflow: Workflow) -> Any:
        """Archive a workflow."""
        return self.repo.archive_workflow(workflow)

    def soft_delete_workflow(self, workflow: Workflow) -> Any:
        """Soft delete a workflow."""
        return self.repo.soft_delete_workflow(workflow)

    def clone_workflow(
        self,
        workflow: Any,
        created_by: Optional[Any] = None,
    ) -> Any:
        """Clone a workflow."""
        return self.repo.clone_workflow(workflow, created_by=created_by)

    # ========================
    # Binding Operations
    # ========================

    def get_bindings(
        self,
        workflow_id: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow bindings with optional filters."""
        return self.repo.get_bindings(
            workflow_id=workflow_id,
            source_type=source_type,
            source_id=source_id,
            workspace_id=workspace_id,
        )

    def get_binding_by_id(self, binding_id: str) -> Optional[Any]:
        """Retrieve a single binding."""
        return self.repo.get_binding_by_id(binding_id)

    def create_binding(
        self,
        workflow_id: str,
        source_type: str,
        trigger_type: str,
        source_id: Optional[str] = None,
        config: Dict[str, Any] = None,
        is_active: bool = True,
    ) -> Any:
        """Create a new workflow binding."""
        return self.repo.create_binding(
            workflow_id=workflow_id,
            source_type=source_type,
            trigger_type=trigger_type,
            source_id=source_id,
            config=config,
            is_active=is_active,
        )

    def delete_binding(self, binding: Any) -> None:
        """Delete a workflow binding."""
        self.repo.delete_binding(binding)

    def set_auto_bindings_active(self, workflow_id: Any, is_active: bool) -> int:
        """Flip the active flag on a workflow's auto-managed trigger bindings.

        Touches only the workspace-wide bindings (``source_id IS NULL``) that
        publish auto-creates; manual source-scoped bindings are untouched.
        Returns the number of bindings updated.
        """
        return self.repo.set_auto_bindings_active(workflow_id, is_active)

    # ========================
    # Run Operations
    # ========================

    def create_runs_with_idempotency(
        self,
        workflow: Any,
        targets: List[Dict[str, str]],
        trigger_type: str,
        trigger_payload: Dict[str, Any] = None,
        idempotency_key: Optional[str] = None,
    ) -> List[str]:
        """Create workflow runs with idempotency support."""
        return self.repo.create_run_with_idempotency(
            workflow=workflow,
            targets=targets,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
            idempotency_key=idempotency_key,
        )

    def get_run_by_id(self, run_id: str) -> Optional[Any]:
        """Retrieve a single run."""
        return self.repo.get_run_by_id(run_id)

    def get_runs(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow runs with optional filters."""
        return self.repo.get_runs(workflow_id=workflow_id, status=status)

    def cancel_run(self, run: Any) -> Any:
        """Cancel a workflow run."""
        return self.repo.cancel_run(run)

    def retry_run(self, run: Any) -> Any:
        """Retry a workflow run."""
        return self.repo.retry_run(run)

    def pause_run(self, run: Any) -> Any:
        """Pause a workflow run."""
        return self.repo.pause_run(run)

    def resume_run(self, run: Any) -> Any:
        """Resume a paused workflow run."""
        return self.repo.resume_run(run)

    # ========================
    # Step State Operations
    # ========================

    def complete_step(
        self,
        run: Any,
        node_id: str,
        output: Dict[str, Any],
        event_type: str = "completed",
    ) -> None:
        """Complete a workflow step."""
        self.repo.complete_step(
            run=run,
            node_id=node_id,
            output=output,
            event_type=event_type,
        )

    def node_exists_in_graph(self, run: WorkflowRun, node_id: str) -> bool:
        """Check if a node exists in the workflow graph."""
        return self.repo.node_exists_in_graph(run, node_id)

    def get_step_events(self, run: WorkflowRun) -> "QuerySet":
        """Retrieve step events for a run."""
        return self.repo.get_step_events(run)

    # ========================
    # Enrollment Operations
    # ========================

    def get_enrollments(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow enrollments."""
        return self.repo.get_enrollments(
            workflow_id=workflow_id,
            status=status,
            target_type=target_type,
        )

    def create_enrollment(
        self,
        workflow_id: str,
        target_type: str,
        target_id: str,
        status: str = "active",
    ) -> Any:
        """Create a new workflow enrollment."""
        return self.repo.create_enrollment(
            workflow_id=workflow_id,
            target_type=target_type,
            target_id=target_id,
            status=status,
        )

    def enroll_targets(
        self,
        workflow: Any,
        targets: List[Dict[str, str]],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enroll targets AND start a run for each one (manual enrollment).

        This is the link that was missing: an enrollment without a run is dead
        state. Manual enrollment skips the trigger and starts the run at the
        ``start`` node. Returns the enrollment rows + the created run ids.
        """
        enrollments = self.repo.enroll_targets(
            workflow_id=str(workflow.id), targets=targets
        )
        run_ids = self.repo.create_run_with_idempotency(
            workflow=workflow,
            targets=targets,
            trigger_type="manual_enroll",
            trigger_payload={"source": "manual_enroll"},
            idempotency_key=idempotency_key or "manual_enroll",
        )
        return {"enrollments": enrollments, "run_ids": run_ids}

    def delete_enrollments(
        self,
        workflow_id: str,
        targets: List[Dict[str, str]],
    ) -> int:
        """Delete workflow enrollments."""
        return self.repo.delete_enrollments(workflow_id, targets)

    def fire_due_schedules(self, now) -> Dict[str, int]:
        """Fire every recurring schedule whose next_run_at has arrived.

        Called by the beat task. Each schedule fires independently — one
        failure is logged and skipped so it never blocks the others. ``now`` is
        passed in by the (infrastructure) task so the application layer stays
        free of Django's timezone import.
        """
        schedule_ids = self.repo.list_due_workflow_schedule_ids(now)
        fired = 0
        for schedule_id in schedule_ids:
            try:
                if self.repo.fire_due_workflow_schedule(schedule_id, now):
                    fired += 1
            except Exception:
                logger.exception(
                    "workflow_schedule_fire_failed schedule_id=%s", schedule_id
                )
        if schedule_ids:
            logger.info(
                "workflow_fire_due_schedules due=%s fired=%s",
                len(schedule_ids),
                fired,
            )
        return {"due": len(schedule_ids), "fired": fired}

    def create_schedule(
        self,
        *,
        workflow: Any,
        now,
        created_by: Any = None,
        cadence: str,
        run_time: Any = None,
        timezone: str = "UTC",
        days_of_week: Optional[List[int]] = None,
        day_of_month: Optional[int] = None,
        interval_minutes: Optional[int] = None,
        audience: Optional[List[Dict[str, str]]] = None,
        enabled: bool = True,
    ) -> Any:
        """Create a recurring schedule, precomputing its first next_run_at.

        ``now`` is injected by the controller so the application layer stays
        free of Django's timezone import; the planner itself is pure domain.
        """
        from components.workflow.domain.services.schedule_planner import (
            compute_next_run,
        )

        next_run_at = compute_next_run(
            cadence=cadence,
            run_time=run_time,
            after=now,
            timezone=timezone or "UTC",
            days_of_week=days_of_week or [],
            day_of_month=day_of_month,
            interval_minutes=interval_minutes,
        )
        return self.repo.create_schedule(
            workflow_id=str(workflow.id),
            workspace_id=str(workflow.workspace_id),
            cadence=cadence,
            run_time=run_time,
            timezone=timezone or "UTC",
            days_of_week=days_of_week or [],
            day_of_month=day_of_month,
            interval_minutes=interval_minutes,
            audience=audience or [],
            enabled=enabled,
            next_run_at=next_run_at,
            created_by=created_by,
        )

    def list_schedules(self, workflow_id: str):
        return self.repo.list_schedules(workflow_id)

    def get_schedule(self, schedule_id: str):
        return self.repo.get_schedule(schedule_id)

    def update_schedule(self, schedule: Any, now, **fields) -> Any:
        return self.repo.update_schedule(schedule, now, **fields)

    def delete_schedule(self, schedule_id: str) -> int:
        return self.repo.delete_schedule(schedule_id)

"""Repository layer for workflow persistence and ORM operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import uuid

from django.db import router, transaction
from django.utils import timezone

from django.db.models import Q

from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowBinding,
    WorkflowEnrollment,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunIdempotency,
    WorkflowSchedule,
    WorkflowStepEvent,
    WorkflowStepState,
    WorkflowTemplate,
    WorkflowVersion,
)


class WorkflowRepository:
    """Repository for workflow domain persistence operations."""

    # ========================
    # Template CRUD Operations
    # ========================

    @staticmethod
    def get_templates(
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
        user: Optional[Any] = None,
    ) -> "QuerySet":
        """Retrieve workflow templates filtered by scope, workspace, and group visibility.

        Args:
            scope: "system", "org", or None for all available
            workspace_id: Workspace UUID to filter by
            user: Current user for group-based visibility filtering

        Returns:
            QuerySet of WorkflowTemplate
        """
        # Trashed templates (recycle bin) never appear in the picker.
        queryset = WorkflowTemplate.objects.filter(is_deleted=False)

        if scope == "system":
            return queryset.filter(is_system=True)
        if scope == "org":
            if not workspace_id:
                return queryset.none()
            queryset = queryset.filter(workspace_id=workspace_id, is_system=False)
            return WorkflowRepository._apply_group_visibility(queryset, workspace_id, user)

        if workspace_id:
            # System templates are always visible to everyone.
            # Use Q objects instead of |-ing querysets to avoid the
            # "Cannot combine a unique query with a non-unique query"
            # error when _apply_group_visibility adds .distinct().
            from django.db.models import Q

            system_ids = list(
                queryset.filter(is_system=True).values_list("id", flat=True)
            )
            org_qs = queryset.filter(workspace_id=workspace_id, is_system=False)
            org_qs = WorkflowRepository._apply_group_visibility(org_qs, workspace_id, user)
            org_ids = list(org_qs.values_list("id", flat=True))

            combined_ids = set(system_ids) | set(org_ids)
            return queryset.filter(id__in=combined_ids)
        return queryset.filter(is_system=True)

    @staticmethod
    def _apply_group_visibility(
        queryset: "QuerySet",
        workspace_id: Optional[str],
        user: Optional[Any],
    ) -> "QuerySet":
        """Filter templates by group-based visibility.

        - Templates with no visible_to_groups are visible to everyone.
        - Templates with visible_to_groups set are only visible to
          members of at least one of those groups, or the workspace owner.
        - Workspace owners always see all templates.
        """
        if not user or not workspace_id:
            return queryset.filter(visible_to_groups__isnull=True).distinct()

        # Check if user is workspace owner — they see everything
        from infrastructure.persistence.workspaces.models import Workspace

        is_owner = Workspace.objects.filter(id=workspace_id, workspace_owner=user).exists()
        if is_owner:
            return queryset

        # Get the user's group IDs within this workspace
        user_group_ids = user.workspace_groups.filter(
            workspace_id=workspace_id
        ).values_list("id", flat=True)

        return queryset.filter(
            Q(visible_to_groups__isnull=True)
            | Q(visible_to_groups__id__in=user_group_ids)
        ).distinct()

    @staticmethod
    def get_template_by_id(template_id: str) -> Optional[WorkflowTemplate]:
        """Retrieve a single template by ID.

        Args:
            template_id: Template ID

        Returns:
            WorkflowTemplate or None
        """
        return WorkflowTemplate.objects.filter(id=template_id, is_deleted=False).first()

    @staticmethod
    def create_template(
        id: str,
        label: str,
        description: str = "",
        category: str = "",
        version: str = "1",
        is_system: bool = False,
        default_graph: Dict[str, Any] = None,
        workspace_id: Optional[str] = None,
        created_by: Optional[Any] = None,
    ) -> WorkflowTemplate:
        """Create a new workflow template.

        Args:
            id: Template ID
            label: Template label
            description: Template description
            category: Template category
            version: Template version
            is_system: Is system template
            default_graph: Default workflow graph
            workspace_id: Workspace UUID (None for system templates)
            created_by: User who created the template

        Returns:
            WorkflowTemplate instance
        """
        return WorkflowTemplate.objects.create(
            id=id,
            label=label,
            description=description,
            category=category,
            version=version,
            is_system=is_system,
            default_graph=default_graph or {},
            workspace_id=workspace_id,
            created_by=created_by,
        )

    # ========================
    # Workflow CRUD Operations
    # ========================

    @staticmethod
    def get_workflows(
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        template_id: Optional[str] = None,
        scheduled: Optional[bool] = None,
        exclude_deleted: bool = True,
    ) -> "QuerySet":
        """Retrieve workflows with optional filters.

        Each row is annotated with ``next_run_at`` — the soonest fire time
        across its *enabled* schedules (None if it has none) — so the list can
        show a "Next run" column and filter to scheduled-only without an N+1.

        Args:
            workspace_id: Filter by workspace
            status: Filter by workflow status
            goal: Filter by workflow goal
            template_id: Filter by template
            scheduled: If True, only workflows with an enabled schedule
            exclude_deleted: Exclude soft-deleted workflows

        Returns:
            QuerySet of Workflow
        """
        from django.db.models import Count, IntegerField, Min, OuterRef, Subquery
        from django.db.models.functions import Coalesce
        from infrastructure.persistence.workspaces.workflows.models import (
            WorkflowRun,
        )

        queryset = Workflow.objects.all()

        if exclude_deleted:
            queryset = queryset.filter(is_deleted=False)

        if workspace_id:
            queryset = queryset.filter(workspace_id=workspace_id)
        if status:
            queryset = queryset.filter(status=status)
        if goal:
            queryset = queryset.filter(goal=goal)
        if template_id:
            queryset = queryset.filter(template_id=template_id)

        # Run-completion counts via correlated subqueries (NOT a Count() across
        # the reverse `runs` join) — the queryset already annotates next_run_at
        # off the `schedules` join, and joining a second reverse relation in one
        # aggregate query multiplies rows and corrupts both counts. Subqueries
        # keep each count independent + N+1-free. Coalesce → 0 for zero-run rows.
        _runs = WorkflowRun.objects.filter(workflow_id=OuterRef("pk"))
        queryset = queryset.annotate(
            next_run_at=Min(
                "schedules__next_run_at",
                filter=Q(schedules__enabled=True),
            ),
            total_runs=Coalesce(
                Subquery(
                    _runs.values("workflow_id")
                    .annotate(c=Count("id"))
                    .values("c"),
                    output_field=IntegerField(),
                ),
                0,
            ),
            completed_runs=Coalesce(
                Subquery(
                    _runs.filter(status="completed")
                    .values("workflow_id")
                    .annotate(c=Count("id"))
                    .values("c"),
                    output_field=IntegerField(),
                ),
                0,
            ),
        )
        if scheduled is True:
            queryset = queryset.filter(next_run_at__isnull=False)

        return queryset.select_related("workspace", "template", "created_by")

    @staticmethod
    def get_workflow_by_id(workflow_id: str) -> Optional[Workflow]:
        """Retrieve a single workflow by ID.

        Args:
            workflow_id: Workflow UUID

        Returns:
            Workflow or None
        """
        return Workflow.objects.select_related("workspace", "template").filter(
            id=workflow_id, is_deleted=False
        ).first()

    @staticmethod
    def create_workflow(
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
    ) -> Workflow:
        """Create a new workflow.

        Args:
            workspace_id: Workspace UUID
            name: Workflow name
            description: Workflow description
            goal: Workflow goal
            template_id: Associated template ID
            is_custom: Is custom workflow
            status: Workflow status (draft, published, etc.)
            version: Workflow version
            graph: Workflow graph JSON
            created_by: User who created the workflow

        Returns:
            Workflow instance
        """
        return Workflow.objects.create(
            workspace_id=workspace_id,
            name=name,
            description=description,
            goal=goal,
            template_id=template_id,
            is_custom=is_custom,
            status=status,
            version=version,
            graph=graph or {},
            created_by=created_by,
        )

    @staticmethod
    def update_workflow(
        workflow: Workflow,
        **kwargs
    ) -> Workflow:
        """Update a workflow with the given fields.

        Args:
            workflow: Workflow instance
            **kwargs: Fields to update

        Returns:
            Updated Workflow instance
        """
        allowed_fields = {
            "name", "description", "goal", "template_id",
            "is_custom", "status", "version", "graph"
        }
        update_fields = [k for k in kwargs.keys() if k in allowed_fields]

        if update_fields:
            for field, value in kwargs.items():
                if field in allowed_fields:
                    setattr(workflow, field, value)
            workflow.save(update_fields=update_fields)

        return workflow

    @staticmethod
    def publish_workflow(
        workflow: Workflow,
        notes: str = "",
        created_by: Optional[Any] = None,
    ) -> Workflow:
        """Publish a workflow version.

        Creates a new WorkflowVersion and updates workflow status.

        Args:
            workflow: Workflow instance
            notes: Version notes
            created_by: User creating the version

        Returns:
            Updated Workflow instance
        """
        next_version = workflow.version + 1

        WorkflowVersion.objects.create(
            workflow=workflow,
            version=next_version,
            notes=notes or "",
            graph=workflow.graph,
            created_by=created_by,
        )

        workflow.status = Workflow.Status.PUBLISHED
        workflow.version = next_version
        workflow.save(update_fields=["status", "version", "updated_at"])

        return workflow

    @staticmethod
    def archive_workflow(workflow: Workflow) -> Workflow:
        """Archive a workflow.

        Args:
            workflow: Workflow instance

        Returns:
            Updated Workflow instance
        """
        workflow.status = Workflow.Status.ARCHIVED
        workflow.save(update_fields=["status", "updated_at"])
        return workflow

    @staticmethod
    def soft_delete_workflow(workflow: Workflow) -> Workflow:
        """Soft delete a workflow.

        Args:
            workflow: Workflow instance

        Returns:
            Updated Workflow instance
        """
        workflow.is_deleted = True
        workflow.deleted_at = timezone.now()
        workflow.save(update_fields=["is_deleted", "deleted_at"])
        return workflow

    @staticmethod
    def clone_workflow(
        workflow: Workflow,
        created_by: Optional[Any] = None,
    ) -> Workflow:
        """Clone a workflow.

        Args:
            workflow: Workflow instance to clone
            created_by: User creating the clone

        Returns:
            New cloned Workflow instance
        """
        clone = Workflow.objects.create(
            workspace=workflow.workspace,
            name=f"{workflow.name} - copy",
            description=workflow.description,
            goal=workflow.goal,
            template=workflow.template,
            is_custom=workflow.is_custom,
            status=Workflow.Status.DRAFT,
            version=1,
            graph=workflow.graph,
            created_by=created_by,
        )
        return clone

    # ========================
    # Binding CRUD Operations
    # ========================

    @staticmethod
    def get_bindings(
        workflow_id: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow bindings with optional filters.

        Args:
            workflow_id: Filter by workflow
            source_type: Filter by source type
            source_id: Filter by source ID
            workspace_id: Filter by workspace

        Returns:
            QuerySet of WorkflowBinding
        """
        queryset = WorkflowBinding.objects.select_related("workflow").all()

        if workflow_id:
            queryset = queryset.filter(workflow_id=workflow_id)
        if source_type:
            queryset = queryset.filter(source_type=source_type)
        if source_id:
            queryset = queryset.filter(source_id=source_id)
        if workspace_id:
            queryset = queryset.filter(workflow__workspace_id=workspace_id)

        return queryset

    @staticmethod
    def get_binding_by_id(binding_id: str) -> Optional[WorkflowBinding]:
        """Retrieve a single binding by ID.

        Args:
            binding_id: Binding UUID

        Returns:
            WorkflowBinding or None
        """
        return WorkflowBinding.objects.select_related("workflow").filter(
            id=binding_id
        ).first()

    @staticmethod
    def create_binding(
        workflow_id: str,
        source_type: str,
        trigger_type: str,
        source_id: Optional[str] = None,
        config: Dict[str, Any] = None,
        is_active: bool = True,
    ) -> WorkflowBinding:
        """Create a new workflow binding.

        Args:
            workflow_id: Workflow UUID
            source_type: Source type (e.g., "feature")
            trigger_type: Trigger type
            source_id: Source ID (optional)
            config: Binding configuration
            is_active: Is binding active

        Returns:
            WorkflowBinding instance
        """
        return WorkflowBinding.objects.create(
            workflow_id=workflow_id,
            source_type=source_type,
            trigger_type=trigger_type,
            source_id=source_id,
            config=config or {},
            is_active=is_active,
        )

    @staticmethod
    def delete_binding(binding: WorkflowBinding) -> None:
        """Delete a workflow binding.

        Args:
            binding: WorkflowBinding instance
        """
        binding.delete()

    @staticmethod
    def set_auto_bindings_active(workflow_id, is_active: bool) -> int:
        """Flip the active flag on a workflow's auto-managed trigger bindings.

        Auto-managed bindings are the workspace-wide ones (``source_id IS NULL``)
        that ``sync_workflow_bindings`` creates on publish. Manually-created,
        source-scoped bindings are left alone. Used by the starter-workflow seed
        to park an ``activate=False`` starter's binding INACTIVE right after
        publish so it appears in the gallery but does not fire until an admin
        turns it on. Returns the number of bindings updated.
        """
        return WorkflowBinding.objects.filter(
            workflow_id=workflow_id, source_id__isnull=True
        ).update(is_active=is_active)

    @staticmethod
    def sync_workflow_bindings(workflow_id, triggers) -> int:
        """Idempotently reconcile a workflow's auto-managed trigger bindings.

        ``triggers`` is a list of ``(source_type, trigger_type)`` pairs derived
        from the start node. This is what makes the start node's trigger picker
        actually wire up: on publish we ensure exactly one ACTIVE binding per
        selected trigger and deactivate any auto-managed binding for a trigger
        that was removed. Only auto-managed bindings (``source_id IS NULL``) are
        touched — manually-created, source-scoped bindings are left alone.

        Returns the number of active trigger bindings after the sync.
        """
        wanted = {(str(s), str(t)) for s, t in triggers if s and t}
        existing = list(
            WorkflowBinding.objects.filter(workflow_id=workflow_id, source_id__isnull=True)
        )
        existing_by_trigger = {b.trigger_type: b for b in existing}

        for source_type, trigger_type in wanted:
            binding = existing_by_trigger.get(trigger_type)
            if binding is None:
                WorkflowBinding.objects.create(
                    workflow_id=workflow_id,
                    source_type=source_type,
                    trigger_type=trigger_type,
                    source_id=None,
                    config={},
                    is_active=True,
                )
            elif not binding.is_active or binding.source_type != source_type:
                binding.is_active = True
                binding.source_type = source_type
                binding.save(update_fields=["is_active", "source_type"])

        wanted_triggers = {t for _, t in wanted}
        for binding in existing:
            if binding.trigger_type not in wanted_triggers and binding.is_active:
                binding.is_active = False
                binding.save(update_fields=["is_active"])

        return len(wanted_triggers)

    # ========================
    # Run Creation & Execution
    # ========================

    @staticmethod
    def create_run_with_idempotency(
        workflow: Workflow,
        targets: List[Dict[str, str]],
        trigger_type: str,
        trigger_payload: Dict[str, Any] = None,
        idempotency_key: Optional[str] = None,
    ) -> List[str]:
        """Create workflow runs with idempotency support.

        Creates a run for each target, checking idempotency key first.
        Uses atomic transaction to ensure consistency.

        Args:
            workflow: Workflow instance
            targets: List of {"target_type": str, "target_id": str}
            trigger_type: Trigger type
            trigger_payload: Trigger payload data
            idempotency_key: Idempotency key (optional)

        Returns:
            List of created run IDs
        """
        run_ids = []

        with transaction.atomic():
            for target in targets:
                target_type = target["target_type"]
                target_id = target["target_id"]
                key = (idempotency_key or "").strip()

                existing = None
                if key:
                    existing = WorkflowRunIdempotency.objects.filter(
                        workflow=workflow,
                        target_type=target_type,
                        target_id=target_id,
                        idempotency_key=key,
                    ).select_related("run").first()

                if existing:
                    run_ids.append(str(existing.run_id))
                    continue

                run = WorkflowRun.objects.create(
                    workflow=workflow,
                    workflow_version=workflow.version,
                    status=WorkflowRun.Status.QUEUED,
                    trigger_type=trigger_type,
                    trigger_payload=trigger_payload or {},
                    target_type=target_type,
                    target_id=target_id,
                )

                if key:
                    WorkflowRunIdempotency.objects.create(
                        workflow=workflow,
                        target_type=target_type,
                        target_id=target_id,
                        idempotency_key=key,
                        run=run,
                    )

                run_ids.append(str(run.id))

        return run_ids

    @staticmethod
    def get_run_by_id(run_id: str) -> Optional[WorkflowRun]:
        """Retrieve a single run by ID.

        Args:
            run_id: Run UUID

        Returns:
            WorkflowRun or None
        """
        return WorkflowRun.objects.select_related("workflow").filter(
            id=run_id
        ).first()

    @staticmethod
    def get_runs(
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow runs with optional filters.

        Args:
            workflow_id: Filter by workflow
            status: Filter by run status

        Returns:
            QuerySet of WorkflowRun
        """
        queryset = WorkflowRun.objects.order_by("-created_at")

        if workflow_id:
            queryset = queryset.filter(workflow_id=workflow_id)
        if status:
            queryset = queryset.filter(status=status)

        return queryset.select_related("workflow")

    @staticmethod
    def cancel_run(run: WorkflowRun) -> WorkflowRun:
        """Cancel a workflow run.

        Args:
            run: WorkflowRun instance

        Returns:
            Updated WorkflowRun instance
        """
        run.status = WorkflowRun.Status.CANCELED
        run.canceled_at = timezone.now()
        run.save(update_fields=["status", "canceled_at"])
        return run

    @staticmethod
    def retry_run(run: WorkflowRun) -> WorkflowRun:
        """Retry a FAILED run from the node that failed — not from the start.

        Resets the failed step back to ``pending`` so the engine re-executes it,
        and points the run at that node. Completed upstream steps keep their
        ``completed`` state, so re-running does NOT re-fire their side effects
        (emails, tasks, tags) — the engine's per-node completed-skip already
        protects them, and resuming AT the failed node means they aren't even
        revisited. Falls back to a full restart only if no failed step is found.

        Returns the run set RUNNING at the resume node.
        """
        alias = router.db_for_write(WorkflowRun)
        with transaction.atomic(using=alias):
            failed_state = (
                WorkflowStepState.objects.using(alias)
                .filter(run=run, status="failed")
                .order_by("-updated_at")
                .first()
            )
            resume_node_id = (
                failed_state.node_id if failed_state else None
            ) or run.current_node_id or ""

            if failed_state is not None:
                failed_state.status = "pending"
                failed_state.last_error = ""
                failed_state.completed_at = None
                failed_state.save(
                    update_fields=[
                        "status",
                        "last_error",
                        "completed_at",
                        "updated_at",
                    ]
                )

            run.status = WorkflowRun.Status.RUNNING
            run.current_node_id = resume_node_id
            run.completed_at = None
            run.started_at = run.started_at or timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "current_node_id",
                    "completed_at",
                    "started_at",
                    "updated_at",
                ]
            )
        return run

    @staticmethod
    def pause_run(run: WorkflowRun) -> WorkflowRun:
        """Pause a workflow run.

        Args:
            run: WorkflowRun instance

        Returns:
            Updated WorkflowRun instance
        """
        run.status = WorkflowRun.Status.PAUSED
        run.paused_at = timezone.now()
        run.save(update_fields=["status", "paused_at"])
        return run

    @staticmethod
    def resume_run(run: WorkflowRun) -> WorkflowRun:
        """Resume a paused workflow run.

        Args:
            run: WorkflowRun instance

        Returns:
            Updated WorkflowRun instance
        """
        run.status = WorkflowRun.Status.RUNNING
        run.paused_at = None
        run.save(update_fields=["status", "paused_at"])
        return run

    # ========================
    # Step State & Events
    # ========================

    @staticmethod
    def complete_step(
        run: WorkflowRun,
        node_id: str,
        output: Dict[str, Any],
        event_type: str = "completed",
    ) -> None:
        """Complete a workflow step with output.

        Updates step state, creates event, and transitions run state.
        Uses atomic transaction with row locks for idempotency.

        Args:
            run: WorkflowRun instance
            node_id: Node ID in workflow graph
            output: Step output data
            event_type: Event type (e.g., "completed")
        """
        graph = run.workflow.graph or {}
        nodes = {
            node.get("id"): node
            for node in graph.get("nodes", [])
            if isinstance(node, dict)
        }
        node = nodes.get(node_id)

        # Route the atomic to the tenant DB the model lives on (TenantRouter); a bare atomic() only covers 'default' and select_for_update would fail. See donation_payment_repository.py for the same fix.
        db_alias = router.db_for_write(WorkflowStepState)
        with transaction.atomic(using=db_alias):
            state, _ = WorkflowStepState.objects.using(db_alias).select_for_update().get_or_create(
                run=run,
                node_id=node_id,
                defaults={"status": "pending"},
            )
            state.output = output
            state.status = "completed"
            state.completed_at = timezone.now()
            state.save(update_fields=["output", "status", "completed_at", "updated_at"])

        WorkflowStepEvent.objects.create(
            run=run,
            node_id=node_id,
            event_type=event_type,
            payload=output,
        )

        # Return graph navigation info for calling layer to handle
        if not node:
            return

        node_type = node.get("type")
        if node_type == "decision":
            # Caller will handle branching via task
            return

        # Find next node in graph
        next_node_id = None
        for edge in graph.get("edges", []):
            if edge.get("from") == node_id:
                next_node_id = edge.get("to")
                break

        if next_node_id:
            run.current_node_id = next_node_id
            run.status = WorkflowRun.Status.RUNNING
            run.paused_at = None
            run.save(update_fields=["current_node_id", "status", "paused_at", "updated_at"])
            # Caller will handle enqueueing next step via task

    @staticmethod
    def node_exists_in_graph(run: WorkflowRun, node_id: str) -> bool:
        """Check if a node exists in the workflow graph.

        Args:
            run: WorkflowRun instance
            node_id: Node ID to check

        Returns:
            True if node exists in graph
        """
        graph = run.workflow.graph or {}
        for node in graph.get("nodes", []):
            if isinstance(node, dict) and node.get("id") == node_id:
                return True
        return False

    @staticmethod
    def get_step_events(
        run: WorkflowRun,
    ) -> "QuerySet":
        """Retrieve step events for a run.

        Args:
            run: WorkflowRun instance

        Returns:
            QuerySet of WorkflowStepEvent ordered by creation
        """
        return WorkflowStepEvent.objects.filter(run=run).order_by("-created_at")

    # ========================
    # Enrollment Operations
    # ========================

    @staticmethod
    def get_enrollments(
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow enrollments with optional filters.

        Args:
            workflow_id: Filter by workflow
            status: Filter by enrollment status
            target_type: Filter by target type

        Returns:
            QuerySet of WorkflowEnrollment
        """
        queryset = WorkflowEnrollment.objects.all()

        if workflow_id:
            queryset = queryset.filter(workflow_id=workflow_id)
        if status:
            queryset = queryset.filter(status=status)
        if target_type:
            queryset = queryset.filter(target_type=target_type)

        return queryset

    @staticmethod
    def create_enrollment(
        workflow_id: str,
        target_type: str,
        target_id: str,
        status: str = "active",
    ) -> WorkflowEnrollment:
        """Create a new workflow enrollment.

        Args:
            workflow_id: Workflow UUID
            target_type: Target type (e.g., "contact")
            target_id: Target ID
            status: Enrollment status

        Returns:
            WorkflowEnrollment instance
        """
        return WorkflowEnrollment.objects.create(
            workflow_id=workflow_id,
            target_type=target_type,
            target_id=target_id,
            status=status,
        )

    @staticmethod
    def enroll_targets(
        workflow_id: str,
        targets: List[Dict[str, str]],
    ) -> List[WorkflowEnrollment]:
        """Idempotently create enrollment rows for the given targets.

        Uses get_or_create so re-enrolling the same target does not raise on the
        ``(workflow, target_type, target_id)`` unique constraint.
        """
        enrollments = []
        for target in targets:
            enrollment, _ = WorkflowEnrollment.objects.get_or_create(
                workflow_id=workflow_id,
                target_type=target.get("target_type"),
                target_id=target.get("target_id"),
                defaults={"status": WorkflowEnrollment.Status.ACTIVE},
            )
            enrollments.append(enrollment)
        return enrollments

    @staticmethod
    def delete_enrollments(
        workflow_id: str,
        targets: List[Dict[str, str]],
    ) -> int:
        """Delete workflow enrollments for given targets.

        Args:
            workflow_id: Workflow UUID
            targets: List of {"target_type": str, "target_id": str}

        Returns:
            Number of enrollments deleted
        """
        removed = 0
        for target in targets:
            deleted, _ = WorkflowEnrollment.objects.filter(
                workflow_id=workflow_id,
                target_type=target.get("target_type"),
                target_id=target.get("target_id"),
            ).delete()
            removed += deleted
        return removed

    # ========================
    # Schedule Operations
    # ========================

    @staticmethod
    def list_due_workflow_schedule_ids(now) -> List[str]:
        """IDs of enabled schedules whose next_run_at has arrived."""
        alias = router.db_for_write(WorkflowSchedule)
        return [
            str(i)
            for i in WorkflowSchedule.objects.using(alias)
            .filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=now)
            .values_list("id", flat=True)
        ]

    @staticmethod
    def fire_due_workflow_schedule(schedule_id: str, now) -> bool:
        """Fire ONE due schedule under a row lock, then advance next_run_at.

        Returns True if this call fired it. The lock (skip_locked) + the
        re-check of (enabled, next_run_at <= now) inside the transaction make
        this safe against two beat workers racing the same schedule; the
        per-fire idempotency key also prevents duplicate runs on retry.
        """
        from components.workflow.domain.services.schedule_planner import (
            compute_next_run,
        )

        alias = router.db_for_write(WorkflowSchedule)
        with transaction.atomic(using=alias):
            schedule = (
                WorkflowSchedule.objects.using(alias)
                .select_for_update(skip_locked=True)
                .filter(
                    id=schedule_id,
                    enabled=True,
                    next_run_at__isnull=False,
                    next_run_at__lte=now,
                )
                .first()
            )
            if schedule is None:
                return False

            workflow = (
                Workflow.objects.using(alias)
                .filter(id=schedule.workflow_id, is_deleted=False)
                .first()
            )
            targets = schedule.audience or []
            fired_slot = schedule.next_run_at
            if (
                workflow is not None
                and workflow.status == Workflow.Status.PUBLISHED
                and targets
            ):
                WorkflowRepository.enroll_targets(
                    workflow_id=str(workflow.id), targets=targets
                )
                WorkflowRepository.create_run_with_idempotency(
                    workflow=workflow,
                    targets=targets,
                    trigger_type="scheduled",
                    trigger_payload={
                        "source": "schedule",
                        "schedule_id": str(schedule.id),
                    },
                    idempotency_key=f"schedule:{schedule.id}:{fired_slot.isoformat()}",
                )

            schedule.last_run_at = now
            schedule.next_run_at = compute_next_run(
                cadence=schedule.cadence,
                run_time=schedule.run_time,
                after=now,
                timezone=schedule.timezone or "UTC",
                days_of_week=schedule.days_of_week or [],
                day_of_month=schedule.day_of_month,
                interval_minutes=schedule.interval_minutes,
            )
            schedule.save(
                update_fields=["last_run_at", "next_run_at", "updated_at"]
            )
            return True

    @staticmethod
    def create_schedule(**fields) -> WorkflowSchedule:
        """Create a schedule row (next_run_at precomputed by the caller)."""
        return WorkflowSchedule.objects.create(**fields)

    @staticmethod
    def list_schedules(workflow_id: str):
        return WorkflowSchedule.objects.filter(workflow_id=workflow_id).order_by(
            "-updated_at"
        )

    @staticmethod
    def get_schedule(schedule_id: str) -> Optional[WorkflowSchedule]:
        return WorkflowSchedule.objects.filter(id=schedule_id).first()

    @staticmethod
    def update_schedule(schedule: WorkflowSchedule, now, **fields) -> WorkflowSchedule:
        """Apply changes; recompute next_run_at if any timing field changed."""
        from components.workflow.domain.services.schedule_planner import (
            compute_next_run,
        )

        timing_keys = {
            "cadence",
            "run_time",
            "timezone",
            "days_of_week",
            "day_of_month",
            "interval_minutes",
        }
        for key, value in fields.items():
            setattr(schedule, key, value)
        if timing_keys & set(fields.keys()):
            schedule.next_run_at = compute_next_run(
                cadence=schedule.cadence,
                run_time=schedule.run_time,
                after=now,
                timezone=schedule.timezone or "UTC",
                days_of_week=schedule.days_of_week or [],
                day_of_month=schedule.day_of_month,
                interval_minutes=schedule.interval_minutes,
            )
        schedule.save()
        return schedule

    @staticmethod
    def delete_schedule(schedule_id: str) -> int:
        deleted, _ = WorkflowSchedule.objects.filter(id=schedule_id).delete()
        return deleted

    # ========================
    # Event Operations
    # ========================

    @staticmethod
    def get_events(
        workspace_id: str,
        status: Optional[str] = None,
    ) -> "QuerySet":
        """Retrieve workflow events.

        Args:
            workspace_id: Workspace UUID
            status: Filter by event status

        Returns:
            QuerySet of WorkflowEvent
        """
        queryset = WorkflowEvent.objects.filter(workspace_id=workspace_id)

        if status:
            queryset = queryset.filter(status=status)

        return queryset.order_by("-created_at")

    @staticmethod
    def create_event(
        workspace_id: str,
        source_type: str,
        trigger_type: str,
        payload: Dict[str, Any] = None,
        source_id: Optional[str] = None,
        idempotency_key: str = "",
    ) -> WorkflowEvent:
        """Create a new workflow event.

        Args:
            workspace_id: Workspace UUID
            source_type: Source type
            trigger_type: Trigger type
            payload: Event payload
            source_id: Source ID (optional)
            idempotency_key: Idempotency key

        Returns:
            WorkflowEvent instance
        """
        return WorkflowEvent.objects.create(
            workspace_id=workspace_id,
            source_type=source_type,
            trigger_type=trigger_type,
            payload=payload or {},
            source_id=source_id,
            idempotency_key=idempotency_key,
            status="pending",
        )

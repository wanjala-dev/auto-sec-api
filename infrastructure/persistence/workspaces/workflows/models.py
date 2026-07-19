"""Workspace-owned workflow models for definitions, execution, and audit trails."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from components.workflow.domain.constants import (
    EVENT_STATUSES,
    NODE_TYPES,
    RUN_STATUSES,
    SOURCE_TYPES,
    STEP_EVENT_TYPES,
    STEP_STATES,
    TARGET_TYPES,
    WORKFLOW_STATUSES,
)


class WorkflowTemplate(models.Model):
    """Reusable workflow blueprint; can be system-wide or workspace-specific."""

    id = models.CharField(primary_key=True, max_length=128)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="workflow_templates",
    )
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=64)
    version = models.CharField(max_length=16, default="1")
    is_system = models.BooleanField(default=False)
    default_graph = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workflow_templates",
    )
    visible_to_groups = models.ManyToManyField(
        "workspaces.WorkspaceGroup",
        blank=True,
        related_name="visible_workflow_templates",
        help_text="Groups that can see this template. Empty means visible to all.",
    )
    # Soft delete → recycle bin (Template Kernel lifecycle). Trashed templates
    # drop out of the gallery + the template picker; restore flips it back.
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("label",)
        indexes = [
            models.Index(fields=["workspace", "category"]),
            models.Index(fields=["is_system"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.version})"


class Workflow(models.Model):
    """Editable workflow definition owned by a workspace."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="workflows",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    goal = models.CharField(max_length=64)
    template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflows",
    )
    is_custom = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=[(value, value) for value in WORKFLOW_STATUSES],
        default=Status.DRAFT,
    )
    version = models.PositiveIntegerField(default=1)
    graph = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workflows",
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["template"]),
        ]

    def __str__(self) -> str:
        return self.name


class WorkflowVersion(models.Model):
    """Immutable snapshot of a published workflow version."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    graph = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_workflow_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)
        unique_together = ("workflow", "version")

    def __str__(self) -> str:
        return f"{self.workflow_id} v{self.version}"


class WorkflowBinding(models.Model):
    """Link a workflow to a feature event trigger."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="bindings",
    )
    source_type = models.CharField(max_length=32, choices=[(v, v) for v in SOURCE_TYPES])
    source_id = models.CharField(max_length=64, null=True, blank=True)
    trigger_type = models.CharField(max_length=64)
    config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workflow", "source_type"]),
            models.Index(fields=["source_type", "source_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_id} -> {self.trigger_type}"


class WorkflowEnrollment(models.Model):
    """Enrollment of a contact or group into a workflow."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        EXITED = "exited", "Exited"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    target_type = models.CharField(max_length=16, choices=[(v, v) for v in TARGET_TYPES])
    target_id = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    entered_at = models.DateTimeField(auto_now_add=True)
    exited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-entered_at",)
        indexes = [
            models.Index(fields=["workflow", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]
        unique_together = ("workflow", "target_type", "target_id")

    def __str__(self) -> str:
        return f"{self.workflow_id}:{self.target_type}:{self.target_id}"


class WorkflowRun(models.Model):
    """Execution of a workflow for a specific target."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELED = "canceled", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    workflow_version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=[(value, value) for value in RUN_STATUSES],
        default=Status.QUEUED,
    )
    trigger_type = models.CharField(max_length=64)
    trigger_payload = models.JSONField(default=dict)
    target_type = models.CharField(max_length=16, choices=[(v, v) for v in TARGET_TYPES])
    target_id = models.CharField(max_length=64)
    current_node_id = models.CharField(max_length=128, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workflow", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.workflow_id}:{self.id}"


class WorkflowRunIdempotency(models.Model):
    """Track run creation keys to avoid duplicate enrollments."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="run_idempotency_keys",
    )
    target_type = models.CharField(max_length=16, choices=[(v, v) for v in TARGET_TYPES])
    target_id = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128)
    run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="idempotency_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workflow", "target_type", "target_id", "idempotency_key")


class WorkflowStepState(models.Model):
    """Execution state for a single node within a run (idempotency anchor)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="step_states",
    )
    node_id = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=[(v, v) for v in STEP_STATES], default="pending")
    attempts = models.PositiveIntegerField(default=0)
    output = models.JSONField(default=dict)
    last_error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("run", "node_id")


class WorkflowStepEvent(models.Model):
    """Append-only audit trail for workflow step transitions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="events",
    )
    node_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=16, choices=[(v, v) for v in STEP_EVENT_TYPES])
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["run", "node_id"]),
        ]


class WorkflowEvent(models.Model):
    """Outbox event emitted by feature modules to trigger workflows."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="workflow_events",
    )
    source_type = models.CharField(max_length=32, choices=[(v, v) for v in SOURCE_TYPES])
    source_id = models.CharField(max_length=64, null=True, blank=True)
    trigger_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=[(v, v) for v in EVENT_STATUSES], default="pending")
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["trigger_type", "source_type"]),
        ]


class WorkflowSchedule(models.Model):
    """Recurring time-based schedule that fires a workflow for a saved audience.

    Distinct from event triggers: a Beat task fires due schedules on a cadence
    and enrolls the saved ``audience`` (a recipient list). ``next_run_at`` is the
    single source of truth for "is this due", and advancing it is what makes a
    fire idempotent against missed/retried Beat ticks.
    """

    class Cadence(models.TextChoices):
        INTERVAL = "interval", "Every N hours"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    # Interval cadence fires every `interval_minutes` from the anchor, with no
    # fixed time-of-day. Floor enforced in the serializer to keep the Beat sweep
    # (which ticks every minute) from being asked to fire faster than it can.
    MIN_INTERVAL_MINUTES = 15

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        Workflow,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="workflow_schedules",
    )
    cadence = models.CharField(max_length=16, choices=Cadence.choices)
    # Weekly: days to fire (0=Monday .. 6=Sunday). Empty for daily/monthly.
    days_of_week = models.JSONField(default=list, blank=True)
    # Monthly: day of month to fire (1-28, capped to avoid month-length gaps).
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
    # Interval: minutes between fires (e.g. 360 = every 6 hours). Null for the
    # fixed-time cadences (daily/weekly/monthly).
    interval_minutes = models.PositiveIntegerField(null=True, blank=True)
    # Fixed time-of-day for daily/weekly/monthly. Null for interval cadence.
    run_time = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    # Saved recipient list: [{"target_type": "contact", "target_id": "<uuid>"}]
    audience = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workflow_schedules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [
            # The due-schedules sweep: WHERE enabled AND next_run_at <= now.
            models.Index(fields=["enabled", "next_run_at"]),
            models.Index(fields=["workspace"]),
            models.Index(fields=["workflow"]),
        ]

    def __str__(self) -> str:
        return f"{self.cadence} schedule for {self.workflow_id}"

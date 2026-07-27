"""ORM for the reversible SOC response action — the execution ledger.

One row per proposed action. It is append-mostly: the lifecycle advances the
``status`` and stamps decision/execution/rollback fields, but ``spec`` and
``inverse_spec`` (the undo, computed at propose time) are written once and never
change — that immutability is what makes the rollback trustworthy. Severity /
approval semantics live in the ``response`` bounded context; this is storage.
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ResponseActionExecution(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed — awaiting human approval"
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        ROLLED_BACK = "rolled_back", "Rolled back"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Relations
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="response_actions")
    # Data
    finding_fingerprint = models.CharField(max_length=255, db_index=True)
    kind = models.CharField(max_length=48)
    spec = models.JSONField()
    inverse_spec = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    dry_run = models.BooleanField(default=True)
    requested_by = models.CharField(max_length=64, blank=True, default="")
    requested_at = models.DateTimeField()
    justification = models.TextField(blank=True, default="")
    decided_by = models.CharField(max_length=64, blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_detail = models.JSONField(default=dict, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rollback_detail = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "status", "-requested_at"]),
            models.Index(fields=["workspace", "finding_fingerprint"]),
        ]
        ordering = ["-requested_at"]

    def __str__(self) -> str:
        return f"{self.kind} [{self.status}] {self.finding_fingerprint}"

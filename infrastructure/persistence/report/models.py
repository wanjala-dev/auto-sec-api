"""Client-deliverable report persistence — the ``report`` bounded context.

A ``Report`` is a workspace-branded, client-deliverable document assembled
from findings already on the SOC board (``project.Task`` rows tagged
``source_type`` ``ai.*``). The first kind is the penetration-test report; the
``report`` context's ``ReportKind`` registry keeps the model kind-agnostic so
compliance / posture / exec-brief reports plug in without a schema change.

Lifecycle mirrors the reports pattern: a row is created ``draft`` →
``generating`` (Celery assembles + renders the PDF) → ``generated`` →
``approved`` (owner/admin sign-off gate) → the PDF is downloadable only once
approved. ``failed`` records a generation error for the operator.

The PDF itself lives in object storage (S3/MinIO) keyed by
``workspace_id/report_id.pdf`` — this row only carries the object key and the
timestamp it was stamped, never the bytes.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Report(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        GENERATED = "generated", "Generated"
        APPROVED = "approved", "Approved"
        FAILED = "failed", "Failed"

    # ── PK ──────────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Relations ───────────────────────────────────────────────────────
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="deliverable_reports",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_deliverable_reports",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_deliverable_reports",
    )

    # ── Data ────────────────────────────────────────────────────────────
    # The report kind id from ``components.report.domain.report_kind`` (e.g.
    # ``pentest``). A CharField, not an enum column — new kinds register in the
    # domain registry, never in a migration.
    kind = models.CharField(max_length=32, default="pentest", db_index=True)
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    # Client + engagement scope the operator supplied at generation time:
    # {client_name, engagement_title, scope_summary, target, approach,
    #  source_types: [...], since, until}. Free-form so a future kind can carry
    # its own scope shape without a migration.
    scope = models.JSONField(default=dict, blank=True)
    # Assembled structured report data (histogram, matrix rows, per-finding
    # technical sections) + the grounded narrative — the exact ground truth the
    # PDF was rendered from. Persisted so a re-render is deterministic and the
    # narrative faithfulness result is auditable.
    assembled = models.JSONField(default=dict, blank=True)
    # How many findings the assembler pulled — surfaced in the list without
    # re-reading ``assembled``.
    finding_count = models.PositiveIntegerField(default=0)
    # Free-form failure detail (truncated traceback) when status == failed.
    error_message = models.TextField(blank=True, default="")

    # ── PDF object storage ──────────────────────────────────────────────
    pdf_key = models.CharField(max_length=512, blank=True, default="")
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    # ── Metadata ────────────────────────────────────────────────────────
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["workspace", "kind", "status"], name="report_ws_kind_status"),
            models.Index(fields=["workspace", "created_at"], name="report_ws_created"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind}/{self.status})"

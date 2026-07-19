"""Security report templates — the report-writing kind of the Template Kernel.

A ``SecurityReportTemplate`` is a reusable skeleton for the documents a SOC /
pentest team writes: penetration-test reports, root-cause analyses, incident
reports, corrective-action plans, threat briefs. System templates (``workspace``
NULL, ``is_seeded`` True) ship with Auto-Sec; a workspace can create its own.

It plugs into the ONE Template Kernel (``components/templates/``) as the
``security_report_template`` kind — the kernel lists it in the unified gallery and
(via the recycle-bin adapter) governs its soft-delete lifecycle. The kernel reads
this model generically through ``apps.get_model`` + field names, so nothing here
imports the kernel.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class SecurityReportTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # NULL workspace == system/global template (the kernel's universal rule).
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="security_report_templates",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Pentest | RCA | Incident | Corrective Action | Threat Brief | …
    category = models.CharField(max_length=64, default="Report")
    # The report skeleton (sections) — used for the gallery preview + as the
    # starting point when a template is applied to a new document.
    body_html = models.TextField(blank=True)
    # Structured section list / variables the authoring flow expands.
    metadata = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    # System templates are platform-owned; the kernel's delete guard refuses to
    # trash them (they'd vanish for every tenant at once).
    is_seeded = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_security_report_templates",
    )
    # Soft delete → recycle bin (Template Kernel lifecycle).
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=["workspace", "is_deleted"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"

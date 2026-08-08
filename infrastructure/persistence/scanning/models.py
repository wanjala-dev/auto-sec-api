"""Generic scan-execution store — ONE table for every scanning pillar.

A ``ScanRun`` is the metadata of a single scanner execution (who/what/when/how
many), regardless of engine — Prowler CSPM, Trivy container SCA, a future OSINT
sweep. The *findings* it produces do NOT live here; they flow to the unified
``findings`` SSOT via ``FindingObserved`` events (ADR 0004 C6: one normalized
finding, no per-pillar finding table). This is deliberately the anti-clone of the
legacy ``cloud_posture`` snapshot tables — a new pillar reuses this row, it does
not add its own.

Pillar-specific richness (a CVE's package/fixed-version, a CSPM check's compliance
map) rides in each SSOT ``Finding``'s ``attributes`` (the OCSF "unmapped" bag),
not in a bespoke column here.
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ScanRun(models.Model):
    """One scanner execution against one target — a point-in-time record."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="scan_runs")

    # The scanner pillar, e.g. "cloud_posture.prowler" / "container_security.trivy".
    # Matches the ``source`` on the findings it emits, so a run and its findings correlate.
    source = models.CharField(max_length=64)
    # What was scanned, in the pillar's terms (an account id, an image reference).
    target_ref = models.CharField(max_length=512, blank=True, default="")

    # Soft references to the integrations connection/account (no cross-context FK).
    connection_id = models.UUIDField(null=True, blank=True)
    account_id = models.CharField(max_length=32, blank=True, default="")

    # Provenance: WHO caused this run. ``trigger`` is the coarse origin
    # ("manual" = an operator pressed scan-now, "schedule" = a beat fan-out);
    # ``triggered_by_id`` is the operator's user id for manual runs (soft
    # reference — no cross-context FK), null for system-initiated ones.
    trigger = models.CharField(max_length=16, default="manual")
    triggered_by_id = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    engine = models.CharField(max_length=32, blank=True, default="")
    engine_version = models.CharField(max_length=64, blank=True, default="")
    error = models.CharField(max_length=255, blank=True, default="")

    # Scan-level counts describe the whole run; the actionable findings are the SSOT's.
    total_checks = models.PositiveIntegerField(default=0)
    passed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="scanrun_ws_created_idx"),
            models.Index(fields=["workspace", "source", "-created_at"], name="scanrun_ws_source_idx"),
        ]

    def __str__(self) -> str:
        return f"ScanRun<{self.source} {self.target_ref[:40]} {self.failed_count}F @ {self.created_at:%Y-%m-%d}>"

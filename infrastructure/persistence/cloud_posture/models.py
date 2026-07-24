"""Cloud-posture persistence — the CSPM snapshot store (Phase 3).

Prowler is the detection engine (open-source, Apache-2.0); this is the store its
output lands in, and the value-add AI layer reads. Per
``docs/plans/SECURITY_POSTURE_VISION_2026-07-20.md`` §3.3/§4.2: a nightly
per-account Prowler scan → a ``CloudPostureScan`` + one ``CloudPostureFinding``
per actionable (non-PASS) check. Workspace-scoped; the live assume-role scan is
gated on the operator's read-only IAM audit-role rollout (this store + the parser
are engine-agnostic and testable against captured Prowler JSON).
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"
    INFORMATIONAL = "informational", "Informational"


class CheckStatus(models.TextChoices):
    PASS = "pass", "Pass"
    FAIL = "fail", "Fail"
    MANUAL = "manual", "Manual"


class CloudPostureScan(models.Model):
    """One Prowler run against one cloud account — a point-in-time snapshot."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="cloud_posture_scans")

    # Soft references to the integrations connection/account (no cross-context FK).
    connection_id = models.UUIDField(null=True, blank=True)
    account_id = models.CharField(max_length=32)
    provider = models.CharField(max_length=16, default="aws")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    # Prowler version / scan provenance for reproducibility.
    engine_version = models.CharField(max_length=32, blank=True, default="")

    total_checks = models.PositiveIntegerField(default=0)
    passed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="cps_scan_ws_created_idx"),
            models.Index(fields=["workspace", "account_id", "-created_at"], name="cps_scan_ws_acct_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"CloudPostureScan<{self.account_id} {self.failed_count}F/{self.total_checks} @ {self.created_at:%Y-%m-%d}>"
        )


class CloudPostureFinding(models.Model):
    """One actionable (non-PASS) Prowler check result within a scan."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="cloud_posture_findings")
    scan = models.ForeignKey(CloudPostureScan, on_delete=models.CASCADE, related_name="findings")

    check_id = models.CharField(max_length=128)
    title = models.CharField(max_length=512, blank=True, default="")
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=8, choices=CheckStatus.choices, default=CheckStatus.FAIL)

    account_id = models.CharField(max_length=32, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    service = models.CharField(max_length=64, blank=True, default="")
    resource_uid = models.CharField(max_length=512, blank=True, default="")
    resource_name = models.CharField(max_length=255, blank=True, default="")
    resource_type = models.CharField(max_length=128, blank=True, default="")

    finding_uid = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    remediation = models.TextField(blank=True, default="")
    compliance = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A check on a given resource is unique within a scan (dedup on re-ingest).
            models.UniqueConstraint(
                fields=["scan", "check_id", "resource_uid"],
                name="uniq_cps_finding_per_scan_check_resource",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "severity", "-created_at"], name="cps_finding_ws_sev_idx"),
            models.Index(fields=["scan", "severity"], name="cps_finding_scan_sev_idx"),
        ]

    def __str__(self) -> str:
        return f"CloudPostureFinding<{self.severity}:{self.check_id} {self.resource_uid[:40]}>"

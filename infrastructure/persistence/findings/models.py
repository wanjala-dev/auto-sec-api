"""Finding — the normalized security-finding SSOT (ADR 0004 D1).

Every scanning pillar (Prowler today; Trivy/Checkov later) projects into this one
table via ``FindingObserved`` → the ``findings`` context, so severity/status/identity
are comparable across pillars and dedup + lifecycle live in one place. The board
``Task`` becomes a *local copy* of a Finding (a later phase), not the finding itself.

Identity is ``(workspace, source, fingerprint)`` — a nightly re-scan of the same
misconfiguration updates ``last_seen_at`` on the existing row instead of creating a
duplicate. ``asset_urn`` is the cross-pillar correlation key (carried by value, no FK
to the graph — ADR 0004 D4).
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class Finding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="findings")

    # Identity — the dedup key. ``source`` is the pillar/scanner ("cloud_posture.prowler").
    source = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=255)
    # Cross-pillar correlation key (AssetUrn.value). Indexed for the graph join.
    asset_urn = models.CharField(max_length=512)

    # Normalized (OCSF-aligned) severity/status — the shared value objects' .value.
    severity = models.CharField(max_length=16)
    status = models.CharField(max_length=16, default="open")

    title = models.CharField(max_length=512)
    description = models.TextField(blank=True, default="")
    remediation = models.TextField(blank=True, default="")
    compliance = models.JSONField(default=dict, help_text="Framework tags, e.g. {'CIS-2.0': ['2.1.5']}.")
    attributes = models.JSONField(default=dict, help_text="Pillar-specific extras.")

    # Lifecycle timestamps, set explicitly by the use case (not auto_now) so a
    # status change never spuriously rewrites the observation window.
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source", "fingerprint"],
                name="uniq_finding_identity",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "severity", "-last_seen_at"], name="finding_ws_sev_seen_idx"),
            models.Index(fields=["workspace", "status", "-last_seen_at"], name="finding_ws_status_seen_idx"),
            models.Index(fields=["workspace", "asset_urn"], name="finding_ws_urn_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"

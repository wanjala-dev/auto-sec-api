"""Code-security pillar persistence — per-repo scan snapshot rows (ADR 0019 P1).

A ``RepoScanSnapshot`` is the scan-level record of one Opengrep run over one repo
at one resolved commit: severity counts for the HUD tile + the commit provenance
every finding of that run shares. Findings themselves live in the findings SSOT
(never a per-pillar finding table — ADR 0004 C6); this row is the pillar's
non-finding by-product, mirroring ``container_security.ImageSbom``.

``scan_run_id`` is a soft reference to ``scanning.ScanRun`` (ADR 0004 C4 — no
cross-context FK).
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class RepoScanSnapshot(models.Model):
    """One row per completed Opengrep scan run — a point-in-time SAST posture record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="repo_scan_snapshots")

    # Soft reference to the producing scanning.ScanRun (no cross-context FK — C4).
    scan_run_id = models.UUIDField(unique=True)

    # What was scanned: the allowlisted repo + the resolved commit the archive was
    # fetched at (every finding of the run carries the same commit_sha).
    repo = models.CharField(max_length=200)
    commit_sha = models.CharField(max_length=64, blank=True, default="")
    engine_version = models.CharField(max_length=32, blank=True, default="")

    # Severity counts for the run (the HUD tile header without querying findings).
    total_findings = models.PositiveIntegerField(default=0)
    critical_count = models.PositiveIntegerField(default=0)
    high_count = models.PositiveIntegerField(default=0)
    medium_count = models.PositiveIntegerField(default=0)
    low_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "repo", "-created_at"], name="reposcan_ws_repo_created_idx"),
        ]

    def __str__(self) -> str:
        return f"RepoScanSnapshot<{self.repo}@{self.commit_sha[:12]} {self.total_findings} findings>"

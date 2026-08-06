"""Container-security pillar persistence — the image-SBOM reference records.

An ``ImageSbom`` is the *reference* to a CycloneDX SBOM a Trivy image scan produced
(task #99 P1): where the body lives in the object store (bucket + key) plus the
metadata the HUD shows without fetching it (package count, size, spec version).
The body itself NEVER lives in Postgres — SBOMs can be MBs; they stay in MinIO/S3
and are served via presigned URLs.

``scan_run_id`` is a soft reference to ``scanning.ScanRun`` (ADR 0004 C4 — no
cross-context FK), mirroring ``ScanRun.connection_id``'s convention.
"""

from __future__ import annotations

import uuid

from django.db import models

from infrastructure.persistence.workspaces.models import Workspace


class ImageSbom(models.Model):
    """One stored SBOM per scan run — a point-in-time bill of materials for an image."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="image_sboms")

    # Soft reference to the producing scanning.ScanRun (no cross-context FK — C4).
    scan_run_id = models.UUIDField(unique=True)

    # What was scanned + the ref digest used in the object key (sha256 hex of image_ref).
    image_ref = models.CharField(max_length=512)
    image_ref_digest = models.CharField(max_length=64, blank=True, default="")

    # SBOM identity + where the body lives.
    format = models.CharField(max_length=16, default="cyclonedx")
    spec_version = models.CharField(max_length=16, blank=True, default="")
    bucket = models.CharField(max_length=128)
    object_key = models.CharField(max_length=512)

    # Display metadata (the HUD's count header without fetching the body).
    size_bytes = models.PositiveBigIntegerField(default=0)
    package_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="imagesbom_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return f"ImageSbom<{self.image_ref[:40]} {self.package_count}pkgs run={str(self.scan_run_id)[:8]}>"

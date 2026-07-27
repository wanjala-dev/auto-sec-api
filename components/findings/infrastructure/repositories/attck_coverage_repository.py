"""Django adapter for AttckCoverageStorePort.

Reads Finding rows (owner-context ORM access is fine here) to aggregate, and
read/writes the materialized ``WorkspaceAttckCoverage`` blob.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.findings.application.ports.attck_coverage_port import (
    AttckCoverageStorePort,
    CoverageSnapshot,
)

_ATTCK_KEY = "MITRE ATT&CK"


class DjangoAttckCoverageRepository(AttckCoverageStorePort):
    def open_finding_attck_tags(self, workspace_id: UUID) -> list[tuple[list[str], str]]:
        from infrastructure.persistence.findings.models import Finding

        rows: list[tuple[list[str], str]] = []
        qs = (
            Finding.objects.filter(workspace_id=workspace_id, status="open")
            .only("compliance", "severity")
            .values_list("compliance", "severity")
        )
        for compliance, severity in qs.iterator(chunk_size=500):
            technique_ids = (compliance or {}).get(_ATTCK_KEY) or []
            if technique_ids:
                rows.append(([str(t) for t in technique_ids], severity or ""))
        return rows

    def save(
        self, workspace_id: UUID, *, coverage: dict, technique_count: int, finding_count: int, computed_at: datetime
    ) -> None:
        from infrastructure.persistence.findings.models import WorkspaceAttckCoverage

        WorkspaceAttckCoverage.objects.update_or_create(
            workspace_id=workspace_id,
            defaults={
                "coverage": coverage,
                "technique_count": technique_count,
                "finding_count": finding_count,
                "computed_at": computed_at,
            },
        )

    def get(self, workspace_id: UUID) -> CoverageSnapshot:
        from infrastructure.persistence.findings.models import WorkspaceAttckCoverage

        row = WorkspaceAttckCoverage.objects.filter(workspace_id=workspace_id).first()
        if row is None:
            return CoverageSnapshot(
                coverage={"tactics": [], "totals": {"techniques": 0, "findings": 0, "tactics": 0}},
                technique_count=0,
                finding_count=0,
                computed_at=None,
            )
        return CoverageSnapshot(
            coverage=row.coverage or {},
            technique_count=row.technique_count,
            finding_count=row.finding_count,
            computed_at=row.computed_at,
        )

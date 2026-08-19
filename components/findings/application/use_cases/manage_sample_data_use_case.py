"""Seed / clear the never-empty-HUD sample findings (onboarding slice B).

Sample findings are written directly through the store (NOT the record-observed
path) so seeding fake data never publishes ``FindingRaised`` — no triage runs, no
Slack alerts on demo data. Every row's source starts with ``sample.`` so clearing
is exact, and seeding is guarded to a workspace with no real findings so it can
never pollute genuine posture data. Findings only (workspace-scoped SSOT, ADR 0004).
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.sample_findings import SAMPLE_FINDINGS
from components.shared_kernel.domain.security import (
    SAMPLE_SOURCE_PREFIX,
    FindingStatus,
    Severity,
)

logger = logging.getLogger(__name__)


class SeedSampleDataUseCase:
    def __init__(self, *, store: FindingStorePort, recompute_coverage=None) -> None:
        self._store = store
        self._recompute = recompute_coverage  # optional AttckCoverage recompute use case

    def execute(self, workspace_id: UUID, *, now: datetime) -> dict:
        # Guard: never seed onto a workspace that already has real findings.
        if self._store.has_real_findings(workspace_id, sample_prefix=SAMPLE_SOURCE_PREFIX):
            logger.info("sample_data seed skipped — workspace has real findings ws=%s", workspace_id)
            return {"seeded": 0, "skipped": True}

        seeded = 0
        for row in SAMPLE_FINDINGS:
            self._store.upsert(
                FindingEntity(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    source=row["source"],
                    fingerprint=row["fingerprint"],
                    asset_urn=row["asset_urn"],
                    severity=Severity(row["severity"]),
                    status=FindingStatus.OPEN,
                    title=row["title"],
                    first_seen_at=now,
                    last_seen_at=now,
                    description=row.get("description", ""),
                    remediation=row.get("remediation", ""),
                    compliance=dict(row.get("compliance", {})),
                    attributes={"sample": True, **dict(row.get("attributes", {}))},
                )
            )
            seeded += 1

        if self._recompute:
            self._recompute.execute(workspace_id, now)
        logger.info("sample_data seeded ws=%s count=%s", workspace_id, seeded)
        return {"seeded": seeded, "skipped": False}


class ClearSampleDataUseCase:
    def __init__(self, *, store: FindingStorePort, recompute_coverage=None) -> None:
        self._store = store
        self._recompute = recompute_coverage

    def execute(self, workspace_id: UUID, *, now: datetime) -> dict:
        deleted = self._store.delete_sample_findings(workspace_id, sample_prefix=SAMPLE_SOURCE_PREFIX)
        if self._recompute:
            self._recompute.execute(workspace_id, now)
        logger.info("sample_data cleared ws=%s deleted=%s", workspace_id, deleted)
        return {"deleted": deleted}

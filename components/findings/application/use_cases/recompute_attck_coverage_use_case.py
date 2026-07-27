"""Recompute a workspace's materialized ATT&CK coverage heatmap (background)."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from components.findings.application.ports.attck_coverage_port import AttckCoverageStorePort
from components.findings.domain.services.attck_coverage_builder import build_attck_coverage

logger = logging.getLogger(__name__)


class RecomputeAttckCoverageUseCase:
    def __init__(self, *, store: AttckCoverageStorePort) -> None:
        self._store = store

    def execute(self, workspace_id: UUID, now: datetime) -> dict:
        entries = self._store.open_finding_attck_tags(workspace_id)
        coverage = build_attck_coverage(entries)
        totals = coverage["totals"]
        self._store.save(
            workspace_id,
            coverage=coverage,
            technique_count=totals["techniques"],
            finding_count=totals["findings"],
            computed_at=now,
        )
        logger.info(
            "attck_coverage_recomputed workspace_id=%s techniques=%s findings=%s",
            workspace_id,
            totals["techniques"],
            totals["findings"],
        )
        return coverage

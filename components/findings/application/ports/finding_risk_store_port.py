"""Port: persistence of the materialized per-finding contextual-risk table (ADR 0013 D3)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from components.findings.domain.services.contextual_risk_scorer import FindingRiskScore


class FindingRiskStorePort(ABC):
    @abstractmethod
    def upsert(
        self,
        *,
        workspace_id: UUID,
        finding_id: UUID,
        score: FindingRiskScore,
        epss_score_date: str | None,
        kev_catalog_version: str | None,
        scored_at: datetime,
    ) -> None:
        """Insert or replace the finding's materialized risk row (recompute-not-increment,
        so a rescore is idempotent). Keyed by ``finding_id`` (OneToOne)."""

    @abstractmethod
    def delete_for_findings(self, workspace_id: UUID, finding_ids: list[UUID]) -> int:
        """Remove risk rows for the given findings (e.g. sample-data teardown). Returns count."""

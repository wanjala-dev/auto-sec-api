"""Django adapter implementing FindingRiskStorePort — writes the materialized risk table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.findings.application.ports.finding_risk_store_port import FindingRiskStorePort
from components.findings.domain.services.contextual_risk_scorer import FindingRiskScore


class FindingRiskRepository(FindingRiskStorePort):
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
        from infrastructure.persistence.findings.models import FindingRisk

        FindingRisk.objects.update_or_create(
            finding_id=finding_id,
            defaults={
                "workspace_id": workspace_id,
                "score": score.value,
                "band": score.band,
                "factors": [
                    {"key": f.key, "label": f.label, "points": f.points, "detail": f.detail} for f in score.factors
                ],
                "epss": score.epss,
                "epss_percentile": score.epss_percentile,
                "in_kev": score.in_kev,
                "exposure": score.exposure,
                "exposure_unknown": score.exposure_unknown,
                "model_version": score.model_version,
                "epss_score_date": epss_score_date or "",
                "kev_catalog_version": kev_catalog_version or "",
                "scored_at": scored_at,
            },
        )

    def delete_for_findings(self, workspace_id: UUID, finding_ids: list[UUID]) -> int:
        from infrastructure.persistence.findings.models import FindingRisk

        if not finding_ids:
            return 0
        deleted, _ = FindingRisk.objects.filter(workspace_id=workspace_id, finding_id__in=finding_ids).delete()
        return deleted

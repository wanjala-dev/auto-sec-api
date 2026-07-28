"""Output DTO — the cloud exposure / asset-inventory summary for the HUD cards."""

from __future__ import annotations

from components.cloud_graph.domain.services.exposure_summary import ExposureSummary


class ExposureSummaryResource:
    @staticmethod
    def of(summary: ExposureSummary) -> dict:
        # {total_assets, exposure:{public,internal,private}, by_type:[{type,count}],
        #  attack_surface:{public_assets, public_at_risk, attack_paths}}
        return summary.to_dict()

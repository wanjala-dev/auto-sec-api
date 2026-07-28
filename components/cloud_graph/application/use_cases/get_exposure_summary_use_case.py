"""Compute the workspace's cloud exposure / asset-inventory summary (CQRS read).

Gathers the inputs through ports — asset counts by exposure + type and the public
asset URNs (cloud_graph store), the URNs of open critical/high findings (findings
context's public store port, C3), and the live attack-path count — then hands them
to the pure ``exposure_summary`` builder. Cheap index-backed aggregates + one set
intersection; no mutation.
"""

from __future__ import annotations

from uuid import UUID

from components.cloud_graph.domain.services.exposure_summary import ExposureSummary, build


class GetExposureSummaryUseCase:
    def __init__(self, *, asset_store, finding_store, attack_path_store) -> None:
        self._assets = asset_store
        self._findings = finding_store
        self._paths = attack_path_store

    def execute(self, workspace_id: UUID) -> ExposureSummary:
        by_exposure = self._assets.count_by_exposure(workspace_id)
        by_type = self._assets.count_by_type(workspace_id, top=8)
        public_urns = set(self._assets.list_public_asset_urns(workspace_id))
        at_risk_urns = self._findings.open_finding_asset_urns(workspace_id, severities=("critical", "high"))
        paths = self._paths.list_for_workspace(workspace_id, limit=200)
        return build(
            by_exposure=by_exposure,
            by_type=by_type,
            public_asset_urns=public_urns,
            at_risk_asset_urns=at_risk_urns,
            attack_path_count=len(paths),
        )

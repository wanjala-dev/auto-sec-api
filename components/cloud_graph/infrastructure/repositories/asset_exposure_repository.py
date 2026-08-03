"""Django adapter implementing AssetExposurePort — the exposure read by asset URN.

A thin, index-backed read over ``CloudAsset`` (indexed on ``(workspace, asset_urn)``).
Sample rows are included deliberately — a demo workspace's exposure is real for scoring
the demo — but soft-deleted assets are excluded.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from components.cloud_graph.application.ports.asset_exposure_port import AssetExposurePort


class AssetExposureRepository(AssetExposurePort):
    def exposure_by_urn(self, workspace_id: UUID, urns: Iterable[str]) -> dict[str, str]:
        urn_list = [u for u in {u.strip() for u in urns if u} if u]
        if not urn_list:
            return {}
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        rows = CloudAsset.objects.filter(
            workspace_id=workspace_id, asset_urn__in=urn_list, is_deleted=False
        ).values_list("asset_urn", "exposure")
        # A URN can (rarely) map to multiple asset rows; keep the most-exposed reading so
        # risk is never under-stated. public > internal > private.
        order = {"public": 3, "internal": 2, "private": 1}
        best: dict[str, str] = {}
        for urn, exposure in rows:
            if order.get(exposure, 0) > order.get(best.get(urn, ""), 0):
                best[urn] = exposure
        return best

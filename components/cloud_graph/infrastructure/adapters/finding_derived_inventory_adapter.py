"""Prowler/SSOT-derived asset inventory (spike §3, Option A).

Builds cloud asset NODES from the cloud-posture findings already in the Finding SSOT —
each carries ``asset_urn`` + ``attributes`` (resource_uid / resource_type / region /
account) from the Prowler run. Reading the SSOT (via the findings context's public
port, C3) rather than cloud_posture's ORM keeps the boundary clean AND reuses the
spine; no new credential path, no new scan.

Known ceiling (accepted for the spike): the SSOT holds resources that produced a
FAILING check — the security-relevant subset, not a full inventory. A complete
inventory (PASS resources + rich relationships/edges) is the CloudQuery/boto3 adapter
(Option B), a later slice. Edges are NOT derived here — Prowler findings are per-resource
checks, not relationships.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from components.cloud_graph.application.ports.asset_inventory_port import (
    AssetInventoryPort,
    AssetSyncResult,
)
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.services.exposure_classifier import classify_exposure
from components.cloud_graph.domain.value_objects.enums import Exposure

logger = logging.getLogger(__name__)

# The cloud pillar whose findings name real cloud resources. Add sources here as more
# cloud scanners land (each must carry resource_uid/resource_type in attributes).
_CLOUD_SOURCE = "cloud_posture.prowler"
_PAGE = 500


class FindingDerivedInventoryAdapter(AssetInventoryPort):
    def __init__(self, *, finding_store=None, asset_store=None):
        self._finding_store = finding_store
        self._asset_store = asset_store

    def _stores(self):
        finding_store = self._finding_store
        asset_store = self._asset_store
        if finding_store is None:
            from components.findings.application.providers.finding_provider import FindingProvider

            finding_store = FindingProvider.build_finding_store()
        if asset_store is None:
            from components.cloud_graph.application.providers.cloud_graph_provider import (
                CloudGraphProvider,
            )

            asset_store = CloudGraphProvider.build_cloud_asset_store()
        return finding_store, asset_store

    def sync_workspace(self, workspace_id: UUID) -> AssetSyncResult:
        finding_store, asset_store = self._stores()

        # Aggregate distinct resources across findings BEFORE upserting: many findings can
        # name one resource, and "most exposed wins" so a later benign finding never
        # downgrades a resource a public-access finding marked PUBLIC.
        assets_by_arn: dict[str, CloudAssetEntity] = {}
        scanned = 0
        offset = 0
        while True:
            page = finding_store.list_findings(workspace_id, source=_CLOUD_SOURCE, limit=_PAGE, offset=offset)
            if not page:
                break
            for finding in page:
                scanned += 1
                asset = self._to_asset(workspace_id, finding)
                if asset is None:
                    continue
                existing = assets_by_arn.get(asset.arn)
                if existing is None or (asset.exposure is Exposure.PUBLIC and existing.exposure is not Exposure.PUBLIC):
                    assets_by_arn[asset.arn] = asset
            if len(page) < _PAGE:
                break
            offset += _PAGE

        for asset in assets_by_arn.values():
            asset_store.upsert_asset(asset)

        logger.info(
            "cloud_graph_inventory_synced workspace_id=%s assets=%d scanned=%d",
            workspace_id,
            len(assets_by_arn),
            scanned,
        )
        return AssetSyncResult(workspace_id=workspace_id, assets_upserted=len(assets_by_arn), findings_scanned=scanned)

    def _to_asset(self, workspace_id: UUID, finding) -> CloudAssetEntity | None:
        attrs = finding.attributes or {}
        arn = str(attrs.get("resource_uid") or finding.asset_urn or "").strip()
        if not arn:
            return None
        resource_type = str(attrs.get("resource_type") or "unknown").strip() or "unknown"
        exposure = classify_exposure(check_id=str(attrs.get("check_id") or ""), resource_type=resource_type)
        return CloudAssetEntity(
            id=uuid4(),
            workspace_id=workspace_id,
            provider="aws",
            arn=arn,
            asset_urn=finding.asset_urn,
            resource_type=resource_type,
            exposure=exposure,
            first_seen_at=finding.first_seen_at,
            last_seen_at=finding.last_seen_at,
            region=str(attrs.get("region") or ""),
            name=str(attrs.get("resource_name") or ""),
            attributes={
                "account_id": str(attrs.get("account_id") or ""),
                "service": str(attrs.get("service") or ""),
                "derived_from": "cloud_posture.prowler",
            },
        )

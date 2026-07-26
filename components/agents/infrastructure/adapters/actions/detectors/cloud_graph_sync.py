"""Cloud asset graph sync detector — materialize the graph on the scheduled cycle.

Slice 2 of the cloud asset graph (spike §5). A driving adapter that refreshes a
workspace's ``CloudAsset`` rows from the Finding SSOT (Prowler-derived), reusing the
detector cycle's per-workspace cadence + the feature-flag gate — the same shape as the
provenance graph-refresh detector (routed through the application layer, not another
context's infra).

It emits NO findings yet (returns ``[]``): this slice only materializes the graph. The
attack-path CTE queries that turn toxic combinations into ``ai.cloud_exposure`` findings
are the next slice (spike §6/§7).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 21600  # self-gate: re-sync at most ~every 6h per workspace


class CloudGraphSyncDetector(BaseDetector):
    slug = "cloud_graph.sync"
    name = "Cloud Asset Graph Sync"
    cadence = "hourly"
    description = "Materializes the cloud asset graph from the Finding SSOT (Prowler-derived)."
    default_config: dict = {}

    def should_run(self, context: DetectorContext) -> bool:
        # Dark until the workspace opts in. Fail closed — never build the graph for a
        # workspace that hasn't enabled it.
        try:
            from components.shared_platform.application.providers.feature_flags_provider import (
                get_feature_flags_provider,
            )

            if not get_feature_flags_provider().is_feature_enabled(
                "feature.cloud_asset_graph", workspace_id=context.workspace_id
            ):
                return False
        except Exception:
            logger.exception("cloud_graph_sync flag check failed workspace=%s", context.workspace_id)
            return False

        # Self-gate frequent cycles: a full re-sync at most ~every 6h per workspace.
        try:
            from django.core.cache import cache

            return bool(cache.add(f"cloud_graph_sync:lease:{context.workspace_id}", "1", _LEASE_SECONDS))
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        try:
            from components.cloud_graph.application.providers.cloud_graph_provider import (
                CloudGraphProvider,
            )

            result = CloudGraphProvider.build_sync_cloud_assets_use_case().execute(context.workspace_id)
            logger.info(
                "cloud_graph_sync workspace=%s assets=%d scanned=%d",
                context.workspace_id,
                result.assets_upserted,
                result.findings_scanned,
            )
        except Exception:
            logger.exception("cloud_graph_sync failed workspace=%s", context.workspace_id)
        return []  # graph materialization only; exposure findings arrive in the CTE slice


registry.register(CloudGraphSyncDetector)

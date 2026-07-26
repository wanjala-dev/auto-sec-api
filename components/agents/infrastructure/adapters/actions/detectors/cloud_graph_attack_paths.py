"""Attack-path correlation detector — materialize ranked toxic paths on the cycle.

The §6 background job (ADR 0004 §6 / ADR 0005 §6). A driving adapter that, after the
graph is synced, runs the AttackPathAnalyzer over a workspace's asset graph and replaces
its materialised ``AttackPath`` rows — reusing the detector cycle's per-workspace cadence
+ feature-flag gate (same shape as ``cloud_graph.sync``). Because the detector cycle runs
in a Celery worker, this satisfies "heavy graph traversal runs in the background", never
inline in a request.

The detector returns ``[]`` on purpose — it does NOT write board cards via the cycle.
Findings are SSOT-native (ADR 0005 phase 3): the materialise use case emits a
``FindingObserved`` per path, the ``findings`` context owner-persists it, and
``FindingRaised`` → ``finding_raised_board_handler`` builds the ``ai.cloud_exposure``
board card (routed to the triage specialist). No legacy cycle dual-write / cutover.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 21600  # self-gate: re-correlate at most ~every 6h per workspace


class CloudGraphAttackPathsDetector(BaseDetector):
    slug = "cloud_graph.attack_paths"
    name = "Cloud Attack-Path Correlation"
    cadence = "hourly"
    description = "Ranks toxic combinations (public → privileged/data) into the materialised attack-path table."
    default_config: dict = {}

    def should_run(self, context: DetectorContext) -> bool:
        # Same gate as the graph sync — dark until the workspace opts in; fail closed.
        try:
            from components.shared_platform.application.providers.feature_flags_provider import (
                get_feature_flags_provider,
            )

            if not get_feature_flags_provider().is_feature_enabled(
                "feature.cloud_asset_graph", workspace_id=context.workspace_id
            ):
                return False
        except Exception:
            logger.exception("cloud_graph_attack_paths flag check failed workspace=%s", context.workspace_id)
            return False

        try:
            from django.core.cache import cache

            return bool(cache.add(f"cloud_graph_attack_paths:lease:{context.workspace_id}", "1", _LEASE_SECONDS))
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        try:
            from django.utils import timezone

            from components.cloud_graph.application.providers.cloud_graph_provider import (
                CloudGraphProvider,
            )

            result = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(
                context.workspace_id, timezone.now()
            )
            logger.info(
                "cloud_graph_attack_paths workspace=%s paths=%d assets=%d edges=%d",
                context.workspace_id,
                result.paths_found,
                result.assets_scanned,
                result.edges_scanned,
            )
        except Exception:
            logger.exception("cloud_graph_attack_paths failed workspace=%s", context.workspace_id)
        return []  # materialisation + AttackPathDetected only; exposure findings are the next slice


registry.register(CloudGraphAttackPathsDetector)

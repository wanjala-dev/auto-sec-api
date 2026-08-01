"""SampleDataService — enable/disable per-workspace sample-data mode (ADR 0011 Phase 1).

The owner-gated demo-mode toggle: flips the ``feature.sample_data_mode`` workspace flag
(the demo-mode SSOT + lever) and seeds/clears the sample dataset. Phase 1 seeds FINDINGS
only, reusing the existing seed/clear use cases; phases 2+ extend this into a cross-context
coordinator that also seeds the cloud graph + logs. Idempotent: seeding skips a workspace
that already has real findings; clearing is delete-by-`sample.` prefix.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SAMPLE_DATA_MODE_FLAG = "feature.sample_data_mode"


@dataclass
class SampleDataService:
    def enable(self, workspace_id, *, now, actor_id=None) -> dict:
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.shared_platform.application.facades.feature_flags_facade import set_workspace_flag

        set_workspace_flag(SAMPLE_DATA_MODE_FLAG, workspace_id, True, updated_by_id=actor_id)
        result = FindingProvider.build_seed_sample_data_use_case().execute(workspace_id, now=now)
        logger.info(
            "sample_data_mode_enabled workspace_id=%s seeded=%s skipped=%s",
            workspace_id,
            result.get("seeded"),
            result.get("skipped"),
        )
        return result

    def disable(self, workspace_id, *, now, actor_id=None) -> dict:
        from components.findings.application.providers.finding_provider import FindingProvider
        from components.shared_platform.application.facades.feature_flags_facade import set_workspace_flag

        set_workspace_flag(SAMPLE_DATA_MODE_FLAG, workspace_id, False, updated_by_id=actor_id)
        result = FindingProvider.build_clear_sample_data_use_case().execute(workspace_id, now=now)
        logger.info("sample_data_mode_disabled workspace_id=%s cleared=%s", workspace_id, result.get("deleted"))
        return result

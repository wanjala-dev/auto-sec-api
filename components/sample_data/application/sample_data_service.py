"""SampleDataService — enable/disable per-workspace sample-data mode (ADR 0011).

The owner-gated demo-mode toggle: flips the ``feature.sample_data_mode`` workspace flag
(the demo-mode SSOT + lever) and seeds/clears the sample dataset across EVERY registered
context through the ``SampleDataFacade`` (findings + cloud graph today; more behind the
same port). Idempotent: each seeder skips a workspace that already has real data for its
context, and clearing is a delete-by-tag per context — so demo and live data never mix.

Phase 2 moved this out of ``findings`` and onto the cross-context coordinator; Phase 3
added the cloud-graph seeder so the asset graph / map / attack surface / risk gauge
populate under demo mode too.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SAMPLE_DATA_MODE_FLAG = "feature.sample_data_mode"


class SampleDataService:
    """Collaborators are injected for testability; both default to the real composition
    root / feature-flag facade so ``SampleDataService()`` (the controller path) just works."""

    def __init__(self, *, facade=None, set_flag=None) -> None:
        if facade is None:
            from components.sample_data.application.providers.sample_data_provider import SampleDataProvider

            facade = SampleDataProvider.build_facade()
        if set_flag is None:
            from components.shared_platform.application.facades.feature_flags_facade import set_workspace_flag

            set_flag = set_workspace_flag
        self._facade = facade
        self._set_flag = set_flag

    def enable(self, workspace_id, *, now, actor_id=None) -> dict:
        self._set_flag(SAMPLE_DATA_MODE_FLAG, workspace_id, True, updated_by_id=actor_id)
        result = self._facade.seed(workspace_id, now=now)
        logger.info("sample_data_mode_enabled workspace_id=%s result=%s", workspace_id, result)
        return result

    def disable(self, workspace_id, *, now, actor_id=None) -> dict:
        self._set_flag(SAMPLE_DATA_MODE_FLAG, workspace_id, False, updated_by_id=actor_id)
        result = self._facade.clear(workspace_id)
        logger.info("sample_data_mode_disabled workspace_id=%s result=%s", workspace_id, result)
        return result

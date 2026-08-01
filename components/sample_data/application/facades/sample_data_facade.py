"""SampleDataFacade — the cross-context sample-data coordinator (ADR 0011 Phase 2).

Fans out over every registered ``SampleDataSeederPort`` so demo mode seeds/tears down
findings + cloud graph (+ future contexts) as ONE set, and reports an aggregate result
keyed by context. The facade knows only the port — each context owns its own data,
tagging, and delete-by-tag — so boundaries stay clean (application → application; no
cross-context infrastructure imports).

Ordering: seed runs seeders in registration order; clear runs them in REVERSE so a
context that depends on another's rows is torn down first (defensive — the current
seeders are independent, but the ordering makes adding a dependent seeder safe).
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from components.sample_data.application.ports.sample_data_seeder_port import SampleDataSeederPort

logger = logging.getLogger(__name__)


class SampleDataFacade:
    def __init__(self, seeders: list[SampleDataSeederPort]) -> None:
        self._seeders = list(seeders)

    def seed(self, workspace_id: UUID, *, now: datetime) -> dict:
        # Workspace-wide mutual-exclusivity pre-flight (ADR 0011 D4): if ANY context holds
        # real data, seed NOTHING — a workspace is either demo or live, never a half-and-half
        # mix. This is the single facade-level decision; the per-seeder guards remain as
        # defense-in-depth.
        real = [s.context for s in self._seeders if s.has_real_data(workspace_id)]
        if real:
            logger.info(
                "sample_data_facade seed skipped workspace_id=%s real_data_in=%s",
                workspace_id,
                ",".join(real),
            )
            return {"seeded": {}, "skipped": "real_data_present", "real_data_in": real}

        results: dict[str, dict] = {}
        for seeder in self._seeders:
            results[seeder.context] = seeder.seed(workspace_id, now=now)
        logger.info(
            "sample_data_facade seeded workspace_id=%s contexts=%s",
            workspace_id,
            ",".join(results.keys()),
        )
        return {"seeded": results}

    def clear(self, workspace_id: UUID) -> dict:
        results: dict[str, dict] = {}
        for seeder in reversed(self._seeders):
            results[seeder.context] = seeder.clear(workspace_id)
        logger.info(
            "sample_data_facade cleared workspace_id=%s contexts=%s",
            workspace_id,
            ",".join(results.keys()),
        )
        return {"cleared": results}

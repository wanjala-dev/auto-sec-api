"""FindingsSampleSeeder — the findings context's SampleDataSeederPort adapter (ADR 0011).

Wraps the existing seed/clear use cases (behavior-identical to Phase 1) so the
cross-context coordinator can drive findings sample data through the shared port.
Seeding writes via ``store.upsert`` directly (never publishing ``FindingRaised``), so
no board/triage/Slack/notification side-effects fire on demo data — the isolation
cornerstone. Tagging + teardown key off the ``sample.`` source prefix.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.sample_data.application.ports.sample_data_seeder_port import SampleDataSeederPort
from components.shared_kernel.domain.security import SAMPLE_SOURCE_PREFIX


class FindingsSampleSeeder(SampleDataSeederPort):
    def __init__(self, *, store: FindingStorePort, seed_use_case, clear_use_case) -> None:
        self._store = store
        self._seed = seed_use_case
        self._clear = clear_use_case

    @property
    def context(self) -> str:
        return "findings"

    def has_real_data(self, workspace_id: UUID) -> bool:
        return self._store.has_real_findings(workspace_id, sample_prefix=SAMPLE_SOURCE_PREFIX)

    def seed(self, workspace_id: UUID, *, now: datetime) -> dict:
        return self._seed.execute(workspace_id, now=now)

    def clear(self, workspace_id: UUID) -> dict:
        from django.utils import timezone

        return self._clear.execute(workspace_id, now=timezone.now())

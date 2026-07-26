"""Composition root for the findings context — wires ports to adapters."""

from __future__ import annotations

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.use_cases.record_observed_finding_use_case import (
    RecordObservedFindingUseCase,
)


class FindingProvider:
    @staticmethod
    def build_record_observed_finding_use_case() -> RecordObservedFindingUseCase:
        from components.findings.infrastructure.repositories.django_finding_repository import (
            DjangoFindingRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return RecordObservedFindingUseCase(
            store=DjangoFindingRepository(),
            event_publisher=CeleryEventPublisher(),
        )

    @staticmethod
    def build_finding_store() -> FindingStorePort:
        """The read/write store — the findings context's public data seam.

        Cross-context readers (e.g. the agents board handler that turns a finding into
        a Kanban card) reach findings through this port, never the ORM (C3: read-only
        cross-component access via a port).
        """
        from components.findings.infrastructure.repositories.django_finding_repository import (
            DjangoFindingRepository,
        )

        return DjangoFindingRepository()

"""Composition root for the findings context — wires ports to adapters."""

from __future__ import annotations

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

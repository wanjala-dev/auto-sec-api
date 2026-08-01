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
    def build_list_findings_use_case():
        """The read-side use case backing the findings list API (CQRS read)."""
        from components.findings.application.use_cases.list_findings_use_case import (
            ListFindingsUseCase,
        )
        from components.findings.infrastructure.repositories.django_finding_repository import (
            DjangoFindingRepository,
        )

        return ListFindingsUseCase(store=DjangoFindingRepository())

    @staticmethod
    def build_recompute_attck_coverage_use_case():
        """The background aggregator that materializes the ATT&CK coverage heatmap."""
        from components.findings.application.use_cases.recompute_attck_coverage_use_case import (
            RecomputeAttckCoverageUseCase,
        )
        from components.findings.infrastructure.repositories.attck_coverage_repository import (
            DjangoAttckCoverageRepository,
        )

        return RecomputeAttckCoverageUseCase(store=DjangoAttckCoverageRepository())

    @staticmethod
    def build_get_attck_coverage_use_case():
        """The read-side use case backing the ATT&CK coverage API (CQRS read)."""
        from components.findings.application.use_cases.get_attck_coverage_use_case import (
            GetAttckCoverageUseCase,
        )
        from components.findings.infrastructure.repositories.attck_coverage_repository import (
            DjangoAttckCoverageRepository,
        )

        return GetAttckCoverageUseCase(store=DjangoAttckCoverageRepository())

    @staticmethod
    def build_get_compliance_summary_use_case():
        """The read use case backing the HUD's Compliance card — distinct failing controls
        per curated framework, rolled up from open findings' compliance tags."""
        from components.findings.application.use_cases.get_compliance_summary_use_case import (
            GetComplianceSummaryUseCase,
        )

        return GetComplianceSummaryUseCase(finding_store=FindingProvider.build_finding_store())

    @staticmethod
    def build_seed_sample_data_use_case():
        """Seed the never-empty-HUD sample findings (onboarding slice B)."""
        from components.findings.application.use_cases.manage_sample_data_use_case import (
            SeedSampleDataUseCase,
        )

        return SeedSampleDataUseCase(
            store=FindingProvider.build_finding_store(),
            recompute_coverage=FindingProvider.build_recompute_attck_coverage_use_case(),
        )

    @staticmethod
    def build_clear_sample_data_use_case():
        """Clear the sample findings (the banner's one-click reset)."""
        from components.findings.application.use_cases.manage_sample_data_use_case import (
            ClearSampleDataUseCase,
        )

        return ClearSampleDataUseCase(
            store=FindingProvider.build_finding_store(),
            recompute_coverage=FindingProvider.build_recompute_attck_coverage_use_case(),
        )

    @staticmethod
    def build_sample_data_seeder():
        """The findings context's SampleDataSeederPort adapter (ADR 0011) — the coordinator
        drives findings sample data through this, wrapping the seed/clear use cases."""
        from components.findings.infrastructure.adapters.findings_sample_seeder import (
            FindingsSampleSeeder,
        )

        return FindingsSampleSeeder(
            store=FindingProvider.build_finding_store(),
            seed_use_case=FindingProvider.build_seed_sample_data_use_case(),
            clear_use_case=FindingProvider.build_clear_sample_data_use_case(),
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

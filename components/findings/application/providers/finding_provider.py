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
        from components.findings.infrastructure.repositories.finding_risk_repository import (
            FindingRiskRepository,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return RecordObservedFindingUseCase(
            store=DjangoFindingRepository(),
            event_publisher=CeleryEventPublisher(),
            risk_store=FindingRiskRepository(),
        )

    @staticmethod
    def build_change_finding_status_use_case():
        """The write-side use case behind the HUD action row — resolve/suppress/reopen a
        finding through the store port (CQRS write). No hard delete: a transition on the
        finding lifecycle, never a row destroy."""
        from components.findings.application.use_cases.change_finding_status_use_case import (
            ChangeFindingStatusUseCase,
        )
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return ChangeFindingStatusUseCase(
            store=FindingProvider.build_finding_store(),
            # Terminal transitions (resolve/suppress) emit FindingResolved so the
            # board can archive the finding's card (suppress) / other lenses react.
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

        return ListFindingsUseCase(
            store=DjangoFindingRepository(),
            triage_states=FindingProvider.build_finding_triage_state_reader(),
        )

    @staticmethod
    def build_get_finding_use_case():
        """The single-finding read behind HUD deep links (CQRS read)."""
        from components.findings.application.use_cases.get_finding_use_case import (
            GetFindingUseCase,
        )

        return GetFindingUseCase(
            store=FindingProvider.build_finding_store(),
            triage_states=FindingProvider.build_finding_triage_state_reader(),
        )

    @staticmethod
    def build_finding_triage_state_reader():
        """Read-only access to each finding's triage state (where it sits between
        "detected" and "fix proposed"). The state is written on the board card by the
        agents pipeline; this composition root picks the adapter that reads it, so the
        read use cases stay ORM-free."""
        from components.findings.infrastructure.repositories.board_triage_state_repository import (
            BoardTriageStateRepository,
        )

        return BoardTriageStateRepository()

    @staticmethod
    def build_recompute_finding_risk_use_case():
        """The background contextual-risk scorer (ADR 0013): reads findings + intel +
        exposure through ports, materializes ``FindingRisk``. Wires the two cross-context
        read seams (VulnIntelPort, AssetExposurePort) via their owning contexts' providers."""
        from components.cloud_graph.application.providers.cloud_graph_provider import (
            CloudGraphProvider,
        )
        from components.findings.application.use_cases.recompute_finding_risk_use_case import (
            RecomputeFindingRiskUseCase,
        )
        from components.findings.infrastructure.repositories.finding_risk_repository import (
            FindingRiskRepository,
        )
        from components.vuln_intel.application.providers.vuln_intel_provider import (
            VulnIntelProvider,
        )

        return RecomputeFindingRiskUseCase(
            finding_store=FindingProvider.build_finding_store(),
            risk_store=FindingRiskRepository(),
            vuln_intel=VulnIntelProvider.build_vuln_intel_port(),
            exposure_port=CloudGraphProvider.build_asset_exposure_port(),
        )

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
    def build_tag_finding_use_case():
        """The write behind the HUD Tag action (ADR 0015 D6): tag/untag a finding.
        Consumes the tagging context's vocabulary ONLY through its provider-built
        ``TagStorePort`` (C3); owns the join edges via ``FindingTagStorePort``."""
        from components.findings.application.use_cases.tag_finding_use_case import TagFindingUseCase
        from components.findings.infrastructure.repositories.finding_tag_repository import (
            FindingTagRepository,
        )
        from components.tagging.application.providers.tagging_provider import TaggingProvider

        return TagFindingUseCase(
            finding_store=FindingProvider.build_finding_store(),
            tag_store=TaggingProvider.build_tag_store(),
            link_store=FindingTagRepository(),
        )

    @staticmethod
    def build_tag_vocabulary_port():
        """The tagging context's ``TagStorePort`` — the ONE seam findings uses to
        resolve tag slugs for the list filter (ADR 0015 D7)."""
        from components.tagging.application.providers.tagging_provider import TaggingProvider

        return TaggingProvider.build_tag_store()

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

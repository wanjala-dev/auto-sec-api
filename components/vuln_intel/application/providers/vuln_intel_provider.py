"""Composition root for the vuln_intel module — wires feed/store/read ports to adapters."""

from __future__ import annotations

from components.vuln_intel.application.ports.vuln_intel_port import VulnIntelPort


class VulnIntelProvider:
    @staticmethod
    def build_refresh_feeds_use_case():
        """The daily beat job's use case: pull EPSS + KEV → dated snapshots, announce refresh."""
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )
        from components.vuln_intel.application.use_cases.refresh_feeds_use_case import RefreshFeedsUseCase
        from components.vuln_intel.infrastructure.adapters.epss_feed_adapter import EpssFeedAdapter
        from components.vuln_intel.infrastructure.adapters.kev_feed_adapter import KevFeedAdapter
        from components.vuln_intel.infrastructure.repositories.vuln_snapshot_repository import (
            VulnSnapshotRepository,
        )

        return RefreshFeedsUseCase(
            epss_feed=EpssFeedAdapter(),
            kev_feed=KevFeedAdapter(),
            store=VulnSnapshotRepository(),
            event_publisher=CeleryEventPublisher(),
        )

    @staticmethod
    def build_vuln_intel_port() -> VulnIntelPort:
        """The read-only enrichment seam other contexts (findings scorer) consume (C3)."""
        from components.vuln_intel.infrastructure.repositories.vuln_intel_read_repository import VulnIntelReader

        return VulnIntelReader()

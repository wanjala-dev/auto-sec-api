"""Composition root for the sample_data context (ADR 0011 Phase 2).

Owns the REGISTRY of which per-context seeders exist and wires them into the
``SampleDataFacade``. Each seeder is built by ITS OWN context's provider (an
application-layer factory), so sample_data never reaches into another context's
infrastructure — it only depends on the other contexts' application-layer providers
and on its own port. Adding a new demo surface = one line here + a builder in that
context's provider.
"""

from __future__ import annotations

from components.sample_data.application.facades.sample_data_facade import SampleDataFacade
from components.sample_data.application.ports.sample_data_seeder_port import SampleDataSeederPort


class SampleDataProvider:
    @staticmethod
    def build_seeders() -> list[SampleDataSeederPort]:
        """The registered per-context seeders, in seed order (findings first so the
        graph/logs can correlate to the same coherent fake account)."""
        from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
        from components.findings.application.providers.finding_provider import FindingProvider

        return [
            FindingProvider.build_sample_data_seeder(),
            CloudGraphProvider.build_sample_data_seeder(),
        ]

    @staticmethod
    def build_facade() -> SampleDataFacade:
        return SampleDataFacade(SampleDataProvider.build_seeders())

"""Composition root — wires the provenance ports to their ORM adapters."""

from __future__ import annotations

from components.provenance.application.service import ProvenanceService
from components.provenance.application.use_cases.refresh_access_graph_use_case import (
    RefreshAccessGraphUseCase,
)


def get_provenance_service() -> ProvenanceService:
    from components.provenance.infrastructure.repositories.django_provenance_repository import (
        DjangoProvenanceRepository,
    )

    return ProvenanceService(graph=DjangoProvenanceRepository())


def get_refresh_access_graph_use_case() -> RefreshAccessGraphUseCase:
    from components.provenance.infrastructure.adapters.django_access_graph_backfill_adapter import (
        DjangoAccessGraphBackfillAdapter,
    )

    return RefreshAccessGraphUseCase(backfill=DjangoAccessGraphBackfillAdapter())

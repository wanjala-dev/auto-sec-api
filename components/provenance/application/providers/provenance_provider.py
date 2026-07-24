"""Composition root — wires the provenance graph port to its ORM adapter."""

from __future__ import annotations

from components.provenance.application.service import ProvenanceService


def get_provenance_service() -> ProvenanceService:
    from components.provenance.infrastructure.repositories.django_provenance_repository import (
        DjangoProvenanceRepository,
    )

    return ProvenanceService(graph=DjangoProvenanceRepository())

"""Composition root for the Tier 3 #14 index-freshness SLO.

Wires the two latest-* ports to their ORM adapters. The Celery beat
task and the management command both call ``measure_index_freshness``
to get a configured use case, so the wiring lives in exactly one
place. Tests inject fakes via the use case constructor directly
without touching this provider.
"""
from __future__ import annotations

from components.knowledge.application.use_cases.measure_index_freshness_use_case import (
    MeasureIndexFreshnessUseCase,
)


def measure_index_freshness() -> MeasureIndexFreshnessUseCase:
    """Return a configured ``MeasureIndexFreshnessUseCase``.

    Lazy imports keep this provider import-light — callers that
    only want the port types can grab them without dragging the
    adapter modules through Django's app registry.
    """
    from components.knowledge.infrastructure.adapters.orm_workspace_event_latest_adapter import (
        OrmWorkspaceEventLatestAdapter,
    )
    from components.knowledge.infrastructure.adapters.pgvector_workspace_index_latest_adapter import (
        PgvectorWorkspaceIndexLatestAdapter,
    )

    return MeasureIndexFreshnessUseCase(
        event_latest_port=OrmWorkspaceEventLatestAdapter(),
        index_latest_port=PgvectorWorkspaceIndexLatestAdapter(),
    )

"""Refresh the access graph from all internal sources (fail-safe per source).

Owns the orchestration policy that used to live in the provenance detector: run
each source's backfill, and if one source errors, log it and continue — a single
failing source must never block the others or the gap detection that follows.
The policy lives here (application layer), not in the detector, so any caller
that needs a fresh graph gets the same guarantee.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from components.provenance.application.ports.access_graph_backfill_port import (
    AccessGraphBackfillPort,
)

logger = logging.getLogger(__name__)


class RefreshAccessGraphUseCase:
    def __init__(self, backfill: AccessGraphBackfillPort):
        self._backfill = backfill

    def execute(self, *, workspace_id: UUID) -> dict[str, dict[str, int]]:
        sources: tuple[tuple[str, Callable[..., dict[str, int]]], ...] = (
            ("audit", self._backfill.backfill_from_audit_log),
            ("memberships", self._backfill.backfill_from_memberships),
            ("ai_findings", self._backfill.backfill_from_ai_findings),
        )
        results: dict[str, dict[str, int]] = {}
        for name, refresh in sources:
            try:
                results[name] = refresh(workspace_id=workspace_id)
            except Exception:
                logger.exception("access_graph_refresh source=%s failed workspace=%s", name, workspace_id)
                results[name] = {}
        return results

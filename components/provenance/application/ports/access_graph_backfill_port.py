"""Port: project the internal source-of-truth systems into the access graph.

The access graph is materialized from three internal sources — the audit trail,
workspace memberships, and AI-agent finding actions. This port is the provenance
context's public seam for *refreshing* that projection; callers (the detector
cycle) drive it through the application layer instead of importing the concrete
backfill services, so no other context couples to provenance infrastructure.

Each method is idempotent (a re-run projects no duplicates) and returns per-kind
counts of rows created plus rows scanned.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class AccessGraphBackfillPort(ABC):
    @abstractmethod
    def backfill_from_audit_log(self, *, workspace_id: UUID) -> dict[str, int]:
        """Project the workspace's audit-trail rows into the graph."""

    @abstractmethod
    def backfill_from_memberships(self, *, workspace_id: UUID) -> dict[str, int]:
        """Project the workspace's memberships (identity grants) into the graph."""

    @abstractmethod
    def backfill_from_ai_findings(self, *, workspace_id: UUID) -> dict[str, int]:
        """Project AI-agent finding actions into the graph."""

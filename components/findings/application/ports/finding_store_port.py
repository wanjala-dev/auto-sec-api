"""Port: persistence of the Finding SSOT, shaped to the application core's needs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.findings.domain.entities.finding_entity import FindingEntity


class FindingStorePort(ABC):
    @abstractmethod
    def find_by_identity(self, workspace_id: UUID, source: str, fingerprint: str) -> FindingEntity | None:
        """Return the finding for the dedup identity (workspace, source, fingerprint), or None."""

    @abstractmethod
    def find_by_id(self, workspace_id: UUID, finding_id: UUID) -> FindingEntity | None:
        """Return the finding by its id (workspace-scoped), or None. Read side."""

    @abstractmethod
    def list_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[FindingEntity]:
        """Return a filtered, paginated page of findings for a workspace (read side).

        Filters AND together; ordered most-recently-seen first. Workspace-scoped by
        construction — a finding for another workspace is never returned.
        """

    @abstractmethod
    def count_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
    ) -> int:
        """Total findings matching the same filter set (for pagination). Read side."""

    @abstractmethod
    def open_finding_asset_urns(self, workspace_id: UUID, *, severities: tuple[str, ...]) -> set[str]:
        """Distinct non-empty asset_urns of OPEN findings at the given severities.

        The cross-pillar correlation read (C4): intersected with the graph's public asset
        URNs to find internet-exposed assets that carry an unresolved critical/high finding.
        """

    @abstractmethod
    def open_finding_compliance(self, workspace_id: UUID) -> list[dict]:
        """The compliance tag bags ({framework: [controls]}) of every OPEN finding — the
        read behind the Compliance card's per-framework failing-control roll-up."""

    @abstractmethod
    def upsert(self, finding: FindingEntity) -> None:
        """Insert or update the finding, keyed by its (workspace, source, fingerprint) identity."""

    @abstractmethod
    def has_real_findings(self, workspace_id: UUID, *, sample_prefix: str) -> bool:
        """True if the workspace has any NON-sample finding — the guard that stops
        sample data from ever landing on a workspace with real findings."""

    @abstractmethod
    def delete_sample_findings(self, workspace_id: UUID, *, sample_prefix: str) -> int:
        """Delete every finding whose source starts with ``sample_prefix``; returns the count."""

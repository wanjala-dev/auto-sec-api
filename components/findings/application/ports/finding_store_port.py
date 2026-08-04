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
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
        limit: int = 25,
        offset: int = 0,
    ) -> list[FindingEntity]:
        """Return a filtered, paginated page of findings for a workspace (read side).

        Filters AND together; ordered most-recently-seen first. Workspace-scoped by
        construction — a finding for another workspace is never returned. Plain entity
        read used by internal consumers (e.g. the cloud_graph inventory sync); the
        risk-ranked API read is ``list_ranked_findings``.

        ``tag_groups`` is an AND of OR-groups of already-slug-resolved tag ids
        (ADR 0015 D7); ``exclude_tag_ids`` are AND-NOT. A group that resolved to
        zero tags matches nothing. The port stays slug-agnostic — slug→id
        resolution happens once at the request layer via ``TagStorePort``.
        """

    @abstractmethod
    def list_ranked_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
        order_by: str = "contextual_risk",
        limit: int = 25,
        offset: int = 0,
    ) -> list[RankedFinding]:
        """Return a filtered, paginated page of findings paired with their contextual-risk
        score (ADR 0013 D4 — the findings-list read). ``order_by="contextual_risk"``
        (default) sorts by the materialized ``FindingRisk.score`` desc (nulls last), else
        most-recently-seen. Each row carries its ``FindingRiskView`` (or None if unscored).
        Tag filters per ``list_findings``; rows carry their live tag refs (chip read)."""

    @abstractmethod
    def iter_scorable_findings(self, workspace_id: UUID, *, finding_id: UUID | None = None) -> Iterator[FindingEntity]:
        """Stream the workspace's findings for (re)scoring (chunked, memory-safe).

        The background contextual-risk job iterates these and writes one ``FindingRisk``
        each. ``finding_id`` narrows to a single finding (the per-event rescore path)."""

    @abstractmethod
    def list_workspace_ids_with_findings(self) -> list[UUID]:
        """Distinct workspace ids that have at least one finding — the fan-out set the
        daily feed-refresh rescore iterates (ADR 0013 D3)."""

    @abstractmethod
    def count_findings(
        self,
        workspace_id: UUID,
        *,
        severity: str | None = None,
        status: str | None = None,
        source: str | None = None,
        asset_urn: str | None = None,
        tag_groups: tuple[tuple[UUID, ...], ...] = (),
        exclude_tag_ids: tuple[UUID, ...] = (),
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

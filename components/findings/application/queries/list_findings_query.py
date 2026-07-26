"""Read-side query + page DTO for listing findings from the SSOT (CQRS read)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.findings.domain.entities.finding_entity import FindingEntity

# Pagination bounds — a list endpoint must paginate (performance rule §11). The
# default is deliberately small; the cap protects the DB from an unbounded page.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


@dataclass(frozen=True)
class ListFindingsQuery:
    """The filters + window for a findings list read. All filters are optional AND-ed."""

    workspace_id: UUID
    severity: str | None = None  # Severity.value
    status: str | None = None  # FindingStatus.value
    source: str | None = None  # pillar/scanner, e.g. "logwatch.error"
    asset_urn: str | None = None
    limit: int = DEFAULT_LIMIT
    offset: int = 0


@dataclass(frozen=True)
class FindingPage:
    """One page of findings plus the total count for the same filter set."""

    items: list[FindingEntity] = field(default_factory=list)
    total: int = 0
    limit: int = DEFAULT_LIMIT
    offset: int = 0

"""Read-side query + page DTO for listing findings from the SSOT (CQRS read).

Findings default to **contextual-risk order** (ADR 0013 D4): the materialized
``FindingRisk.score`` desc, so the list leads with the few that matter, not recency.
``-last_seen_at`` stays available as an explicit option. Each row carries its
``FindingRiskView`` (score, band, EPSS %, KEV, exposure, factors) so the list *shows why*
it's ranked where it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.findings.domain.entities.finding_entity import FindingEntity

# Pagination bounds — a list endpoint must paginate (performance rule §11). The
# default is deliberately small; the cap protects the DB from an unbounded page.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

# Sort keys the read supports. contextual_risk is the default (ADR 0013 D4).
ORDER_CONTEXTUAL_RISK = "contextual_risk"
ORDER_LAST_SEEN = "last_seen"
VALID_ORDER_BY = frozenset({ORDER_CONTEXTUAL_RISK, ORDER_LAST_SEEN})


@dataclass(frozen=True)
class ListFindingsQuery:
    """The filters + window for a findings list read. All filters are optional AND-ed."""

    workspace_id: UUID
    severity: str | None = None  # Severity.value
    status: str | None = None  # FindingStatus.value
    source: str | None = None  # pillar/scanner, e.g. "logwatch.error"
    asset_urn: str | None = None
    order_by: str = ORDER_CONTEXTUAL_RISK
    limit: int = DEFAULT_LIMIT
    offset: int = 0


@dataclass(frozen=True)
class FindingRiskView:
    """The materialized contextual-risk read for one finding (ADR 0013). None when the
    finding has not been scored yet (a fresh finding before the recompute job runs)."""

    score: float
    band: str
    epss: float | None
    epss_percentile: float | None
    in_kev: bool
    exposure: str
    exposure_unknown: bool
    factors: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RankedFinding:
    """A finding paired with its contextual-risk score (the ranked read row)."""

    finding: FindingEntity
    risk: FindingRiskView | None = None


@dataclass(frozen=True)
class FindingPage:
    """One page of ranked findings plus the total count for the same filter set."""

    items: list[RankedFinding] = field(default_factory=list)
    total: int = 0
    limit: int = DEFAULT_LIMIT
    offset: int = 0

"""Collapse a workspace's history into DISTINCT decisions (ADR 0033 D3).

Mining raw rows into cases is the obvious implementation and the wrong one.
Measured on the live demo workspace on 2026-08-21:

    2,881 findings — 1,646 suppressed
    1,645 of those share ONE reason string and ONE minute (2026-08-09 22:10)

That is a single bulk action — "demo scan of public image, no remediation
target" — applied to 1,645 rows. A miner that counted rows would build a suite
of 1,645 cases that are the same case, run the agent against it 1,645 times,
and report a pass rate over a denominator of 1,645. The number would look
authoritative and mean nothing, which is worse than reporting nothing.

The webinar's diversity stage and ADR 0033 D9's claim tiers both exist to stop
exactly this. D9 governs how many observations a claim needs; this module
governs what counts as an observation in the first place. A denominator built
from duplicates defeats the tiers entirely — 1,645 clears AGGREGATE_THRESHOLD
while carrying one decision's worth of information.

The grouping key is deliberately blunt: same source, same normalised reason,
same decision minute. Bulk actions are machine-fast and share their rationale
verbatim; genuine judgements made minutes apart on different findings do not
collide. Where the heuristic is unsure it SPLITS rather than merges, because
under-counting evidence is the safe direction — it lowers the claim tier, and
D9 already refuses to conclude from too little.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

#: Decisions within the same minute, sharing a rationale, are one action.
_BULK_WINDOW_SECONDS = 60

_WHITESPACE = re.compile(r"\s+")


def normalise_reason(reason: str | None) -> str:
    """Casefold and collapse whitespace so trivial edits do not fake variety."""
    if not reason:
        return ""
    return _WHITESPACE.sub(" ", reason.strip()).casefold()


@dataclass(frozen=True)
class DecisionRecord:
    """One human decision drawn from history, before diversity is applied."""

    source_ref: str
    source_kind: str
    reason: str
    decided_at: datetime | None
    label: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DistinctDecision:
    """One distinct decision, and the rows that shared it."""

    representative: DecisionRecord
    duplicate_count: int

    @property
    def scenario(self) -> str:
        reason = self.representative.reason.strip()
        if not reason:
            return f"{self.representative.source_kind} decision (no rationale recorded)"
        return reason[:200]


@dataclass(frozen=True)
class AvailabilityReport:
    """What a workspace HAS, stated so it cannot be mistaken for what it can claim.

    ``raw_rows`` is included precisely because it is the misleading number. A
    surface that shows it alone invites "1,646 cases available!" when the
    answer is two.
    """

    raw_rows: int
    distinct_decisions: int
    largest_cluster: int
    shortfall: int

    @property
    def is_sufficient(self) -> bool:
        return self.shortfall <= 0

    def as_dict(self) -> dict:
        return {
            "raw_rows": self.raw_rows,
            "distinct_decisions": self.distinct_decisions,
            "largest_cluster": self.largest_cluster,
            "shortfall": self.shortfall,
            "is_sufficient": self.is_sufficient,
        }


def _bucket(record: DecisionRecord) -> tuple:
    if record.decided_at is None:
        # No timestamp: fall back to source + reason alone. Splitting further
        # would invent variety we cannot evidence.
        stamp = None
    else:
        stamp = int(record.decided_at.timestamp()) // _BULK_WINDOW_SECONDS
    return (record.source_kind, normalise_reason(record.reason), record.label, stamp)


def collapse_to_distinct(records: list[DecisionRecord]) -> list[DistinctDecision]:
    """Group records into distinct decisions, preserving order of first sight.

    The earliest record in each group is the representative, so a case always
    points at the decision that actually happened first rather than an
    arbitrary member of the cluster.
    """
    groups: dict[tuple, list[DecisionRecord]] = defaultdict(list)
    order: list[tuple] = []
    for record in records:
        key = _bucket(record)
        if key not in groups:
            order.append(key)
        groups[key].append(record)

    distinct: list[DistinctDecision] = []
    for key in order:
        members = groups[key]
        earliest = min(
            members,
            key=lambda r: (r.decided_at is None, r.decided_at or datetime.min),
        )
        distinct.append(DistinctDecision(representative=earliest, duplicate_count=len(members)))
    return distinct


def availability(records: list[DecisionRecord], *, required: int) -> AvailabilityReport:
    """How much genuinely distinct evidence a workspace has, and what is missing."""
    distinct = collapse_to_distinct(records)
    largest = max((d.duplicate_count for d in distinct), default=0)
    return AvailabilityReport(
        raw_rows=len(records),
        distinct_decisions=len(distinct),
        largest_cluster=largest,
        shortfall=max(0, required - len(distinct)),
    )


__all__ = [
    "AvailabilityReport",
    "DecisionRecord",
    "DistinctDecision",
    "availability",
    "collapse_to_distinct",
    "normalise_reason",
]

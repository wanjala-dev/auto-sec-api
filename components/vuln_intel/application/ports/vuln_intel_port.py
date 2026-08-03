"""VulnIntelPort — the read-only enrichment seam the risk scorer consumes (ADR 0013 D2/D3).

This is ``vuln_intel``'s public read contract: given a CVE id, answer "what is its EPSS
probability?" and "is it in CISA KEV?" over the *latest* dated snapshot. The ``findings``
scorer depends on THIS port (a cross-context read-only query, ADR 0004 C3) — it never
imports ``vuln_intel`` infrastructure or its ORM.

Single-CVE methods (``epss`` / ``in_kev``) are the ADR-named contract; the batch methods
(``epss_scores`` / ``kev_members``) exist so a workspace-wide rescore reads all intel in
two queries, not N (performance.md §1). ``version_stamp`` lets the scorer record which
snapshot a score was computed against (reproducibility + audit — ADR 0013 D6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from components.vuln_intel.domain.value_objects.epss_score import EpssScore


@dataclass(frozen=True)
class VulnIntelVersion:
    """Which snapshots the current reads resolve to — stamped onto every scored row."""

    epss_score_date: str | None = None
    kev_catalog_version: str | None = None


class VulnIntelPort(ABC):
    @abstractmethod
    def epss(self, cve: str) -> EpssScore | None:
        """The CVE's EPSS reading in the latest snapshot, or None if absent/unknown."""

    @abstractmethod
    def in_kev(self, cve: str) -> bool:
        """True if the CVE is in the latest CISA KEV snapshot (confirmed exploited)."""

    @abstractmethod
    def epss_scores(self, cves: Iterable[str]) -> dict[str, EpssScore]:
        """Batch EPSS lookup — ``{cve: EpssScore}`` for the CVEs present in the snapshot."""

    @abstractmethod
    def kev_members(self, cves: Iterable[str]) -> set[str]:
        """Batch KEV membership — the subset of ``cves`` present in the latest KEV snapshot."""

    @abstractmethod
    def version_stamp(self) -> VulnIntelVersion:
        """The feed versions the reads currently resolve to (for reproducibility stamps)."""

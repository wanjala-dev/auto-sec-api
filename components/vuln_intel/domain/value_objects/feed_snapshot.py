"""Feed snapshot domain objects — the shape a ``VulnFeedPort`` adapter returns.

A pull of a threat-intel feed is an immutable, version-stamped set of records. The
adapters (EPSS CSV, KEV JSON) map their native format into these; the ingest use case
persists them as a dated snapshot (ADR 0013 D2). Frozen, framework-free — no Django,
no I/O; the adapter does the network + parsing, the domain just holds the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class EpssRecord:
    """One CVE's EPSS reading in a pull."""

    cve: str
    epss: float
    percentile: float

    def __post_init__(self) -> None:
        if not self.cve:
            raise ValueError("EpssRecord.cve is required")


@dataclass(frozen=True)
class KevRecord:
    """One CVE with evidence of active exploitation in a KEV pull."""

    cve: str
    date_added: date | None = None
    known_ransomware: bool = False

    def __post_init__(self) -> None:
        if not self.cve:
            raise ValueError("KevRecord.cve is required")


@dataclass(frozen=True)
class EpssFeedSnapshot:
    """A dated EPSS pull: the feed's own ``score_date`` + ``model_version`` + its records."""

    score_date: date
    model_version: str
    records: tuple[EpssRecord, ...] = field(default_factory=tuple)
    checksum: str = ""

    @property
    def record_count(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class KevFeedSnapshot:
    """A versioned KEV pull: the catalog's own ``catalogVersion`` + its records."""

    catalog_version: str
    records: tuple[KevRecord, ...] = field(default_factory=tuple)
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.catalog_version:
            raise ValueError("KevFeedSnapshot.catalog_version is required")

    @property
    def record_count(self) -> int:
        return len(self.records)

"""Feed snapshot domain objects — the shape a ``VulnFeedPort`` adapter returns.

A pull of a threat-intel feed is an immutable, version-stamped set of records. The
adapters (EPSS CSV, KEV JSON) map their native format into these; the ingest use case
persists them as a dated snapshot (ADR 0013 D2). Frozen, framework-free — no Django,
no I/O; the adapter does the network + parsing, the domain just holds the result.
"""

from __future__ import annotations

from collections.abc import Iterable, Sized
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
    """A dated EPSS pull: the feed's own ``score_date`` + ``model_version`` + its records.

    ``records`` is an ``Iterable`` — either a materialized ``tuple`` (small pulls, tests) or
    a **lazily-streamed, single-consumption iterator** (production: ~280k CVEs). The store
    consumes it exactly once in bounded batches so the ~280k EPSS rows never all live in RAM
    at once (they used to, OOM-killing the 768Mi worker on the real feed). Treat a streamed
    snapshot as write-once: don't re-iterate ``records`` or call ``record_count`` on it — the
    store reports the true count after the stream drains.
    """

    score_date: date
    model_version: str
    records: Iterable[EpssRecord] = field(default_factory=tuple)
    checksum: str = ""

    @property
    def record_count(self) -> int:
        # Meaningful only for a materialized (Sized) snapshot. A streamed snapshot's count is
        # known only once the store drains it, so guard rather than consume the iterator here.
        return len(self.records) if isinstance(self.records, Sized) else 0


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

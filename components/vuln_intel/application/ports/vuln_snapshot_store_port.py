"""VulnSnapshotStorePort — persistence of the dated feed snapshots (write + latest read)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.vuln_intel.domain.value_objects.feed_snapshot import EpssFeedSnapshot, KevFeedSnapshot


class VulnSnapshotStorePort(ABC):
    @abstractmethod
    def save_epss_snapshot(self, snapshot: EpssFeedSnapshot) -> int:
        """Persist an EPSS pull as an immutable dated snapshot, keyed by ``score_date``.

        Idempotent: a same-day re-pull replaces that date's child score rows atomically
        (never a partial overwrite) so scoring always reads a complete snapshot. Returns
        the number of score rows persisted."""

    @abstractmethod
    def save_kev_snapshot(self, snapshot: KevFeedSnapshot) -> int:
        """Persist a KEV pull as an immutable snapshot, keyed by ``catalog_version``.

        Idempotent on the catalog version (same version → replace its entries). Returns
        the number of entry rows persisted."""

    @abstractmethod
    def prune_snapshots(self, *, keep: int = 7) -> int:
        """Retain the ``keep`` most-recent EPSS + KEV snapshots, deleting older ones (and
        their child rows, by cascade). Bounds unbounded growth — EPSS lands ~280k child
        rows/day and the reader only ever uses the latest snapshot. Idempotent; returns the
        number of snapshot rows deleted."""

    @abstractmethod
    def latest_epss_score_date(self) -> str | None:
        """ISO ``score_date`` of the newest EPSS snapshot, or None if none ingested yet."""

    @abstractmethod
    def latest_kev_catalog_version(self) -> str | None:
        """``catalog_version`` of the newest KEV snapshot, or None if none ingested yet."""

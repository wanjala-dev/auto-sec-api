"""Refresh the threat-intel feeds into dated snapshots (ADR 0013 D2) — framework-free.

Orchestrates one pull per feed behind its ``VulnFeedPort`` adapter and persists each as
an immutable, version-stamped snapshot through the store port. One feed's failure must
not sink the other (EPSS and KEV are independent sources), so each is guarded and the
result reports what landed. Emits ``VulnIntelRefreshed`` so the ``findings`` context can
rescore (a CVE can newly enter KEV or its EPSS can jump without any finding changing) —
the emitter never imports the subscriber (ADR 0004 C1: the event lives in the shared kernel).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from components.shared_kernel.domain.events import VulnIntelRefreshed
from components.vuln_intel.application.ports.vuln_feed_port import EpssFeedPort, KevFeedPort
from components.vuln_intel.application.ports.vuln_snapshot_store_port import VulnSnapshotStorePort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshFeedsResult:
    epss_score_date: str | None = None
    epss_records: int = 0
    kev_catalog_version: str | None = None
    kev_records: int = 0
    errors: tuple[str, ...] = ()


class RefreshFeedsUseCase:
    def __init__(
        self,
        *,
        epss_feed: EpssFeedPort,
        kev_feed: KevFeedPort,
        store: VulnSnapshotStorePort,
        event_publisher=None,
    ) -> None:
        self._epss_feed = epss_feed
        self._kev_feed = kev_feed
        self._store = store
        self._publisher = event_publisher

    def execute(self) -> RefreshFeedsResult:
        epss_date: str | None = None
        epss_count = 0
        kev_version: str | None = None
        kev_count = 0
        errors: list[str] = []

        try:
            epss = self._epss_feed.fetch()
            epss_count = self._store.save_epss_snapshot(epss)
            epss_date = epss.score_date.isoformat()
            logger.info("vuln_intel_epss_refreshed score_date=%s records=%s", epss_date, epss_count)
        except Exception as exc:  # one feed down must not sink the other
            logger.exception("vuln_intel_epss_refresh_failed")
            errors.append(f"epss: {exc}")

        try:
            kev = self._kev_feed.fetch()
            kev_count = self._store.save_kev_snapshot(kev)
            kev_version = kev.catalog_version
            logger.info("vuln_intel_kev_refreshed catalog_version=%s records=%s", kev_version, kev_count)
        except Exception as exc:
            logger.exception("vuln_intel_kev_refresh_failed")
            errors.append(f"kev: {exc}")

        # Announce the refresh so downstream risk rescoring can react. Best-effort: a
        # mis-wired publisher must never fail the ingest that already persisted.
        if self._publisher is not None and (epss_date or kev_version):
            self._publisher.publish(
                VulnIntelRefreshed(
                    epss_score_date=epss_date or "",
                    kev_catalog_version=kev_version or "",
                )
            )

        return RefreshFeedsResult(
            epss_score_date=epss_date,
            epss_records=epss_count,
            kev_catalog_version=kev_version,
            kev_records=kev_count,
            errors=tuple(errors),
        )

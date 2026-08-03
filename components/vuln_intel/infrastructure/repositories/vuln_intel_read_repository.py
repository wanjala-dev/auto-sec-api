"""VulnIntelReader — the read-only enrichment adapter (implements VulnIntelPort).

Resolves the latest EPSS + KEV snapshots once (at construction) and answers CVE lookups
against them. The scorer holds one reader per recompute so the "latest snapshot" is
consistent across a whole workspace's rescore, and batch reads keep it to two queries.
"""

from __future__ import annotations

from collections.abc import Iterable

from components.vuln_intel.application.ports.vuln_intel_port import VulnIntelPort, VulnIntelVersion
from components.vuln_intel.domain.value_objects.epss_score import EpssScore


class VulnIntelReader(VulnIntelPort):
    def __init__(self) -> None:
        self._epss_snapshot_id, self._epss_score_date = self._latest_epss()
        self._kev_snapshot_id, self._kev_catalog_version = self._latest_kev()

    @staticmethod
    def _latest_epss():
        from infrastructure.persistence.vuln_intel.models import EpssSnapshot

        row = EpssSnapshot.objects.order_by("-score_date").values("id", "score_date").first()
        if not row:
            return None, None
        return row["id"], row["score_date"].isoformat()

    @staticmethod
    def _latest_kev():
        from infrastructure.persistence.vuln_intel.models import KevSnapshot

        row = KevSnapshot.objects.order_by("-fetched_at").values("id", "catalog_version").first()
        if not row:
            return None, None
        return row["id"], row["catalog_version"]

    def epss(self, cve: str) -> EpssScore | None:
        if not cve or self._epss_snapshot_id is None:
            return None
        from infrastructure.persistence.vuln_intel.models import EpssScore as EpssScoreModel

        row = (
            EpssScoreModel.objects.filter(snapshot_id=self._epss_snapshot_id, cve=cve)
            .values("epss", "percentile")
            .first()
        )
        return EpssScore(score=row["epss"], percentile=row["percentile"]) if row else None

    def in_kev(self, cve: str) -> bool:
        if not cve or self._kev_snapshot_id is None:
            return False
        from infrastructure.persistence.vuln_intel.models import KevEntry

        return KevEntry.objects.filter(snapshot_id=self._kev_snapshot_id, cve=cve).exists()

    def epss_scores(self, cves: Iterable[str]) -> dict[str, EpssScore]:
        cve_list = [c for c in {c.strip() for c in cves if c} if c]
        if not cve_list or self._epss_snapshot_id is None:
            return {}
        from infrastructure.persistence.vuln_intel.models import EpssScore as EpssScoreModel

        rows = EpssScoreModel.objects.filter(snapshot_id=self._epss_snapshot_id, cve__in=cve_list).values(
            "cve", "epss", "percentile"
        )
        return {r["cve"]: EpssScore(score=r["epss"], percentile=r["percentile"]) for r in rows}

    def kev_members(self, cves: Iterable[str]) -> set[str]:
        cve_list = [c for c in {c.strip() for c in cves if c} if c]
        if not cve_list or self._kev_snapshot_id is None:
            return set()
        from infrastructure.persistence.vuln_intel.models import KevEntry

        return set(
            KevEntry.objects.filter(snapshot_id=self._kev_snapshot_id, cve__in=cve_list).values_list("cve", flat=True)
        )

    def version_stamp(self) -> VulnIntelVersion:
        return VulnIntelVersion(
            epss_score_date=self._epss_score_date,
            kev_catalog_version=self._kev_catalog_version,
        )

"""Recompute the materialized per-finding contextual-risk scores (ADR 0013 D3).

The heavy 4-signal blend runs here, in the background, writing the ``FindingRisk`` read
table — never inline in a request (§6 HARD RULE). Framework-free: it reads findings
through ``FindingStorePort``, EPSS/KEV through the cross-context ``VulnIntelPort``, and
exposure through the cross-context ``AssetExposurePort`` (both read-only, by CVE / AssetUrn
identity — C3/C4), scores each finding with the pure ``ContextualRiskScorer``, and upserts
through ``FindingRiskStorePort`` (recompute-not-increment → idempotent).

Two entry shapes share this one use case (DRY): a whole-workspace rescore (feed refresh /
on-demand) and a single-finding rescore (a ``FindingRaised``/``FindingResolved`` event).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime
from itertools import islice
from uuid import UUID

from components.cloud_graph.application.ports.asset_exposure_port import AssetExposurePort
from components.findings.application.ports.finding_risk_store_port import FindingRiskStorePort
from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.domain.services.contextual_risk_scorer import extract_cve, score_finding
from components.vuln_intel.application.ports.vuln_intel_port import VulnIntelPort

logger = logging.getLogger(__name__)

# Score in bounded batches so a huge workspace never materializes every finding + all of
# its intel/exposure maps into RAM at once (performance.md §5 / ADR 0013 D3). The
# cross-context reads are batched PER CHUNK, keeping them to a small constant per batch.
_CHUNK_SIZE = 500


class RecomputeFindingRiskUseCase:
    def __init__(
        self,
        *,
        finding_store: FindingStorePort,
        risk_store: FindingRiskStorePort,
        vuln_intel: VulnIntelPort,
        exposure_port: AssetExposurePort,
    ) -> None:
        self._findings = finding_store
        self._risk = risk_store
        self._intel = vuln_intel
        self._exposure = exposure_port

    def execute(self, workspace_id: UUID, now: datetime, *, finding_id: UUID | None = None) -> int:
        version = self._intel.version_stamp()  # one snapshot resolution for the whole run
        scored = 0
        for batch in _chunked(self._findings.iter_scorable_findings(workspace_id, finding_id=finding_id), _CHUNK_SIZE):
            scored += self._score_batch(workspace_id, batch, version=version, now=now)

        logger.info(
            "finding_risk_recomputed workspace_id=%s scored=%s single=%s epss_date=%s kev_version=%s",
            workspace_id,
            scored,
            finding_id is not None,
            version.epss_score_date,
            version.kev_catalog_version,
        )
        return scored

    def _score_batch(self, workspace_id, batch, *, version, now) -> int:
        # Batch the cross-context reads for THIS chunk (two intel queries + one exposure
        # query), not N per finding — the scorer then works from in-memory maps
        # (performance.md §1); memory stays bounded to one chunk (§5).
        cves = {cve for f in batch if (cve := extract_cve(f.attributes))}
        urns = {f.asset_urn for f in batch if f.asset_urn}
        epss_map = self._intel.epss_scores(cves)
        kev_set = self._intel.kev_members(cves)
        exposure_map = self._exposure.exposure_by_urn(workspace_id, urns)

        for finding in batch:
            cve = extract_cve(finding.attributes)
            epss_obj = epss_map.get(cve) if cve else None
            cvss_base = _as_float(finding.attributes.get("cvss_base"))
            result = score_finding(
                severity=finding.severity,
                cvss_base=cvss_base,
                has_cve=cve is not None,
                epss=epss_obj.score if epss_obj else None,
                epss_percentile=epss_obj.percentile if epss_obj else None,
                in_kev=cve in kev_set if cve else False,
                exposure=exposure_map.get(finding.asset_urn),
            )
            self._risk.upsert(
                workspace_id=workspace_id,
                finding_id=finding.id,
                score=result,
                epss_score_date=version.epss_score_date,
                kev_catalog_version=version.kev_catalog_version,
                scored_at=now,
            )
        return len(batch)


def _chunked(iterable, size: int) -> Iterator[list]:
    """Yield successive ``size``-length lists from ``iterable`` (bounded memory)."""
    iterator = iter(iterable)
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            return
        yield batch


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

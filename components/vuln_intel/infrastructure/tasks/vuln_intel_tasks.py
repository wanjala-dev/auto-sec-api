"""Celery beat task: refresh the threat-intel feeds off the request path (ADR 0013 D2).

``vuln_intel.refresh_feeds`` runs ~daily (EPSS refreshes daily; KEV a few times/week),
pulls each feed behind its ``VulnFeedPort`` adapter, and lands an immutable dated
snapshot. On success the use case publishes ``VulnIntelRefreshed`` so the findings
context can rescore (the daily-feed-move recompute trigger, ADR 0013 D3). Idempotent —
a same-version re-pull replaces that version's rows, so re-running is safe.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="vuln_intel.refresh_feeds", soft_time_limit=600, time_limit=660)
def refresh_feeds() -> dict:
    from components.vuln_intel.application.providers.vuln_intel_provider import VulnIntelProvider

    logger.info("vuln_intel_refresh_feeds started")
    result = VulnIntelProvider.build_refresh_feeds_use_case().execute()
    logger.info(
        "vuln_intel_refresh_feeds completed epss_score_date=%s epss_records=%s kev_version=%s kev_records=%s errors=%s",
        result.epss_score_date,
        result.epss_records,
        result.kev_catalog_version,
        result.kev_records,
        len(result.errors),
    )
    return {
        "success": not result.errors,
        "epss_score_date": result.epss_score_date,
        "epss_records": result.epss_records,
        "kev_catalog_version": result.kev_catalog_version,
        "kev_records": result.kev_records,
        "errors": list(result.errors),
    }

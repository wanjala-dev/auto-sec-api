"""Handlers: recompute contextual risk when a finding changes or the feeds refresh (ADR 0013 D3).

Two triggers keep the materialized ``FindingRisk`` table current — both dispatch the heavy
blend to Celery, never running it inline:

- ``FindingRaised`` / ``FindingResolved`` → rescore *that one* finding (its severity/CVE/
  status changed).
- ``VulnIntelRefreshed`` → rescore *every workspace with findings*, because a CVE can newly
  enter KEV or its EPSS can jump without any finding changing.

Following the sanctioned application-handler pattern (see remediation_capture_handler): the
Celery task module is imported lazily inside the body so this application module carries no
eager infrastructure/celery import, and dispatch is deferred to ``on_commit``.
"""

from __future__ import annotations

import logging

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised, FindingResolved, VulnIntelRefreshed

logger = logging.getLogger(__name__)


@subscribes_to(FindingRaised)
@subscribes_to(FindingResolved)
def rescore_changed_finding(event) -> None:
    """A finding was raised/resolved → rescore just that finding."""
    from components.shared_kernel.application.transactional import on_commit

    workspace_id = str(event.workspace_id)
    finding_id = str(event.finding_id)
    try:
        from components.findings.infrastructure.tasks.finding_risk_tasks import rescore_finding

        on_commit(lambda: rescore_finding.apply_async(kwargs={"workspace_id": workspace_id, "finding_id": finding_id}))
    except Exception:
        logger.exception("finding_risk_rescore_dispatch_failed workspace_id=%s finding_id=%s", workspace_id, finding_id)


@subscribes_to(VulnIntelRefreshed)
def rescore_all_workspaces_on_feed_refresh(event: VulnIntelRefreshed) -> None:
    """A fresh EPSS/KEV snapshot landed → fan out a per-workspace risk recompute."""
    from components.findings.application.providers.finding_provider import FindingProvider

    workspace_ids = FindingProvider.build_finding_store().list_workspace_ids_with_findings()
    logger.info(
        "finding_risk_feed_refresh_fanout workspaces=%s epss_date=%s kev_version=%s",
        len(workspace_ids),
        event.epss_score_date,
        event.kev_catalog_version,
    )
    for workspace_id in workspace_ids:
        _enqueue_workspace_recompute(str(workspace_id))


def _enqueue_workspace_recompute(workspace_id: str) -> None:
    try:
        from components.findings.infrastructure.tasks.finding_risk_tasks import recompute_finding_risk

        recompute_finding_risk.apply_async(kwargs={"workspace_id": workspace_id})
    except Exception:
        logger.exception("finding_risk_recompute_dispatch_failed workspace_id=%s", workspace_id)

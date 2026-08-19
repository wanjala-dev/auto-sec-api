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
    """A fresh EPSS/KEV snapshot landed → fan out a per-workspace risk recompute.

    "Every workspace with findings" means every TENANT's, and that is why this
    walks the tenant scopes instead of trusting the binding it inherited.

    The feeds are GLOBAL REFERENCE DATA: EPSS and KEV are identical for every
    customer, so ``vuln_intel.refresh_feeds`` runs ONCE, bound to the pooled
    console. The event it publishes therefore arrives here stamped pooled — and a
    dedicated-tier tenant's findings live in their own database, so listing
    workspaces under the inherited binding would silently rescore only the pool.
    Those customers' risk scores would then sit frozen against a snapshot that
    has moved: a CVE entering KEV, or an EPSS jump, would never reach them, and
    every log line would still read "fanout workspaces=N".

    Verified on the live cluster 2026-08-19 — the pool holds 10,261 findings
    across 6 workspaces and each dedicated database answers separately, so the
    partition is real, not theoretical.
    """
    from components.findings.application.providers.finding_provider import FindingProvider
    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        scheduled_sweep_scopes,
    )

    total = 0
    for scope in scheduled_sweep_scopes():
        scoped = 0
        try:
            with scope.bind():
                workspace_ids = FindingProvider.build_finding_store().list_workspace_ids_with_findings()
                scoped = len(workspace_ids)
                for workspace_id in workspace_ids:
                    # Enqueued INSIDE the binding so the message carries this
                    # tenant's headers and the worker rescores the right database.
                    _enqueue_workspace_recompute(str(workspace_id))
        except Exception:
            # One tenant's unreachable database must not stop the rest of the
            # fleet from being rescored against the new snapshot.
            logger.exception(
                "finding_risk_feed_refresh_scope_failed tenant=%s db_alias=%s",
                scope.label,
                scope.db_alias,
            )
            continue
        total += scoped
        logger.info("finding_risk_feed_refresh_fanout tenant=%s workspaces=%s", scope.label, scoped)

    logger.info(
        "finding_risk_feed_refresh_fanout_complete workspaces=%s epss_date=%s kev_version=%s",
        total,
        event.epss_score_date,
        event.kev_catalog_version,
    )


def _enqueue_workspace_recompute(workspace_id: str) -> None:
    try:
        from components.findings.infrastructure.tasks.finding_risk_tasks import recompute_finding_risk

        recompute_finding_risk.apply_async(kwargs={"workspace_id": workspace_id})
    except Exception:
        logger.exception("finding_risk_recompute_dispatch_failed workspace_id=%s", workspace_id)

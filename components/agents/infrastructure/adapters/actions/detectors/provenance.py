"""Provenance detector — refresh the access graph, then flag unused grants.

Runs inside the scheduled detector cycle (hourly-leased). Two jobs, in order:

1. Refresh the workspace's provenance/access graph from the three internal
   sources (audit trail, memberships, AI-agent finding actions) so the graph
   the queries read is fresh. The backfill services are idempotent — a re-run
   projects no duplicates.
2. Compute least-privilege gaps (active grants with no observed use in the
   window) and emit each as a finding. The gap between *potential* (grants) and
   *actual* (events) is the signal.

Pure ORM + arithmetic — no LLM. Not auto-routed (``agent_type=None``):
least-privilege remediation is a human decision (revoke or justify), not an
auto-fix. Findings dedupe on ``lookup_key`` so a persistently-unused grant
raises exactly one card.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 3600  # self-gate: refresh + detect at most hourly per workspace


class ProvenanceLeastPrivilegeDetector(BaseDetector):
    slug = "ai_findings.provenance_least_privilege"
    name = "Provenance Least-Privilege Detector"
    cadence = "hourly"
    description = "Refreshes the access graph and flags grants unused within the window."
    default_config = {"unused_days": 30, "max_findings": 25}

    def should_run(self, context: DetectorContext) -> bool:
        # Keep the feature dark until the workspace opts in (scope-freeze). Fail
        # closed — if the flag can't be resolved, don't populate graphs / raise
        # findings for a workspace that hasn't enabled provenance.
        try:
            from components.shared_platform.application.providers.feature_flags_provider import (
                get_feature_flags_provider,
            )

            if not get_feature_flags_provider().is_feature_enabled(
                "feature.provenance_graph", workspace_id=context.workspace_id
            ):
                return False
        except Exception:
            logger.exception("provenance_detector flag check failed workspace=%s", context.workspace_id)
            return False

        # Self-gate frequent cycles: refresh + detect at most hourly per workspace.
        try:
            from django.core.cache import cache

            return bool(cache.add(f"provenance_detector:lease:{context.workspace_id}", "1", _LEASE_SECONDS))
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        cfg = {**self.default_config, **(self.config or {})}
        workspace_id = context.workspace_id

        self._refresh_graph(workspace_id)

        try:
            from components.provenance.application.providers.provenance_provider import (
                get_provenance_service,
            )

            gaps = get_provenance_service().least_privilege_gaps(
                workspace_id=workspace_id, unused_days=int(cfg.get("unused_days", 30))
            )
        except Exception:
            logger.exception("provenance_detector gaps query failed workspace=%s", workspace_id)
            return []

        max_findings = int(cfg.get("max_findings", 25))
        results: list[DetectorResult] = []
        for gap in gaps[:max_findings]:
            actor, resource, grant = gap.actor, gap.resource, gap.grant
            actor_label = actor.display_name or actor.external_ref
            resource_label = resource.display_name or resource.external_ref
            perms = ", ".join(str(p) for p in grant.permissions) or "access"
            fingerprint = f"provenance_least_privilege:{actor.id}:{resource.id}:{grant.scope}"
            title = f"Unused {'admin ' if grant.is_admin else ''}grant: {actor_label}"
            summary = (
                f"{actor_label} holds [{perms}] on {resource_label} but has not exercised it in "
                f"{gap.unused_days}+ days. Review whether this grant is still needed (least privilege)."
            )
            results.append(
                DetectorResult(
                    action_type="provenance_least_privilege",
                    title=title[:255],
                    summary=summary,
                    payload={
                        "lookup_key": fingerprint,
                        "signal": title,
                        "confidence": "high",
                        "actor": {
                            "id": str(actor.id),
                            "type": str(actor.actor_type),
                            "ref": actor.external_ref,
                            "name": actor.display_name,
                        },
                        "resource": {
                            "id": str(resource.id),
                            "type": resource.resource_type,
                            "ref": resource.external_ref,
                        },
                        "permissions": [str(p) for p in grant.permissions],
                        "scope": grant.scope,
                        "source": grant.source,
                        "unused_days": gap.unused_days,
                        "evidence": [
                            f"grant source: {grant.source or 'unknown'}",
                            f"no observed use in {gap.unused_days}+ days",
                        ],
                    },
                    context={"kind": "least_privilege", "workspace_id": str(workspace_id)},
                    detector_slug=self.slug,
                    agent_type=None,
                    metadata={"impact_score": 60 if grant.is_admin else 30},
                )
            )

        logger.info(
            "provenance_detector workspace=%s gaps=%d emitted=%d",
            workspace_id,
            len(gaps),
            len(results),
        )
        return results

    def _refresh_graph(self, workspace_id) -> None:
        """Idempotently project the three internal sources into the graph.

        Drives provenance's application layer — the fail-safe-per-source policy
        (one source erroring never blocks the others or the gap detection that
        follows) lives in the ``RefreshAccessGraphUseCase``, not here.
        """
        from components.provenance.application.providers.provenance_provider import (
            get_refresh_access_graph_use_case,
        )

        get_refresh_access_graph_use_case().execute(workspace_id=workspace_id)


registry.register(ProvenanceLeastPrivilegeDetector)

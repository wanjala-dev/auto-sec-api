"""Cloud-posture detector — surface actionable Prowler findings on the board.

Reads the actionable ``CloudPostureFinding`` rows from recent scans and emits one
board finding per (account, check, resource). Prowler is the engine; this makes
its output triageable — the value-add AI layer (triage grounds/prioritizes,
posture agent narrates) lives on top. Findings dedupe on ``lookup_key`` so a
persistently-failing check raises exactly one card across nightly scans.

Pure ORM + arithmetic — no LLM. Not auto-routed (``agent_type=None``): cloud
misconfig remediation is a human/IaC decision, not an in-band auto-fix. Gated on
``feature.cloud_posture`` (fail-closed).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from components.agents.domain.detectors.base import BaseDetector, DetectorContext, DetectorResult
from components.agents.infrastructure.adapters.actions.detectors import registry

logger = logging.getLogger(__name__)

_LEASE_SECONDS = 3600
_IMPACT = {"critical": 90, "high": 70, "medium": 40, "low": 20, "informational": 10}
_SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "informational": 1}


class CloudPostureDetector(BaseDetector):
    slug = "ai_findings.cloud_posture"
    name = "Cloud Posture Detector"
    cadence = "hourly"
    description = "Surfaces actionable Prowler CSPM findings from recent scans onto the triage board."
    # 26h window catches the latest nightly scan; cap keeps a firehose off the board.
    default_config = {"window_hours": 26, "max_findings": 50}

    def should_run(self, context: DetectorContext) -> bool:
        try:
            from components.shared_platform.application.providers.feature_flags_provider import (
                get_feature_flags_provider,
            )

            flags = get_feature_flags_provider()
            if not flags.is_feature_enabled("feature.cloud_posture", workspace_id=context.workspace_id):
                return False
            # ADR 0004 Phase 3c: when the board is driven from the Finding SSOT (the
            # FindingRaised board handler), this detector stands down so the two never
            # both file cards. Flip the flag back and this resumes — reversible.
            if flags.is_feature_enabled("feature.cloud_posture_board_from_findings", workspace_id=context.workspace_id):
                return False
        except Exception:
            logger.exception("cloud_posture_detector flag check failed workspace=%s", context.workspace_id)
            return False

        try:
            from django.core.cache import cache

            return bool(cache.add(f"cloud_posture_detector:lease:{context.workspace_id}", "1", _LEASE_SECONDS))
        except Exception:
            return True

    def execute(self, context: DetectorContext) -> Iterable[DetectorResult]:
        from infrastructure.persistence.cloud_posture.models import CloudPostureFinding

        cfg = {**self.default_config, **(self.config or {})}
        window_start = context.run_at - timedelta(hours=int(cfg.get("window_hours", 26)))

        rows = list(
            CloudPostureFinding.objects.filter(
                workspace_id=context.workspace_id, scan__created_at__gte=window_start
            ).select_related("scan")
        )
        # Worst-first, then newest, so the cap keeps the criticals.
        rows.sort(key=lambda f: (_SEVERITY_RANK.get(f.severity, 0), f.created_at), reverse=True)
        rows = rows[: int(cfg.get("max_findings", 50))]

        results: list[DetectorResult] = []
        for finding in rows:
            resource_label = finding.resource_name or finding.resource_uid or "resource"
            fingerprint = f"cloud_posture:{finding.account_id}:{finding.check_id}:{finding.resource_uid}"
            title = f"{finding.severity.title()}: {finding.title or finding.check_id}"
            summary = (
                f"{finding.title or finding.check_id} — {resource_label} "
                f"({finding.region or 'global'}, acct {finding.account_id or '?'}). "
                f"{finding.remediation}".strip()
            )
            results.append(
                DetectorResult(
                    action_type="cloud_posture",
                    title=title[:255],
                    summary=summary,
                    payload={
                        "lookup_key": fingerprint,
                        "signal": title,
                        "confidence": "high",
                        "check_id": finding.check_id,
                        "severity": finding.severity,
                        "account_id": finding.account_id,
                        "region": finding.region,
                        "service": finding.service,
                        "resource_uid": finding.resource_uid,
                        "resource_type": finding.resource_type,
                        "compliance": finding.compliance,
                        "remediation": finding.remediation,
                        "evidence": [
                            f"check: {finding.check_id}",
                            f"resource: {finding.resource_uid}",
                            f"severity: {finding.severity}",
                        ],
                    },
                    context={"kind": "cloud_posture", "workspace_id": str(context.workspace_id)},
                    detector_slug=self.slug,
                    agent_type=None,
                    metadata={"impact_score": _IMPACT.get(finding.severity, 40)},
                )
            )

        logger.info(
            "cloud_posture_detector workspace=%s findings=%d emitted=%d",
            context.workspace_id,
            len(rows),
            len(results),
        )
        return results


registry.register(CloudPostureDetector)

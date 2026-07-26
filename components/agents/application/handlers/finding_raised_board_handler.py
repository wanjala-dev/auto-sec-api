"""Surface a raised finding onto the board as a local-copy Task (ADR 0004 Phase 3).

When a finding is raised in the SSOT, this creates/updates the Kanban card — the *local
copy* (C7), stamped with ``finding_id`` so it references its finding (debt #4). This is
the sole board-surfacing path for cloud-posture findings: the ``CloudPostureDetector``
it replaced (which read ``CloudPostureFinding`` directly — the debt-#3 cross-context ORM
import) was retired once the SSOT cutover was verified. It reproduces that detector's
card shape (``source_type`` / ``agent_type`` / idempotency ``lookup_key`` / title) so the
retirement neither duplicated nor changed a card.

Reads the finding's full detail through the findings context's port (C3: read-only
cross-component access via a port, never its ORM). Only ``cloud_posture.prowler`` is
board-surfaced today; other sources no-op until they're mapped.
"""

from __future__ import annotations

import logging

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised

logger = logging.getLogger(__name__)

_IMPACT = {"critical": 90, "high": 70, "medium": 40, "low": 20, "informational": 10}

# Per finding-source board labels — the retired detector's exact labels, so the cards
# group identically. Extend as more scanning pillars surface findings on the board.
_SOURCE_BOARD = {
    "cloud_posture.prowler": {
        "source_type": "ai.cloud_posture",
        "detector_key": "ai_findings.cloud_posture",
    },
}


@subscribes_to(FindingRaised)
def handle_finding_raised_board(event: FindingRaised) -> None:
    mapping = _SOURCE_BOARD.get(event.source)
    if mapping is None:
        return  # this source is not board-surfaced yet

    from components.agents.application.facades.ai_teammate_facade import ensure_agents_board
    from components.agents.application.handlers.specialist_persistence_service import (
        persist_finding_as_task,
    )
    from components.agents.infrastructure.services.agents_board_service import SUGGESTED
    from components.findings.application.providers.finding_provider import FindingProvider
    from infrastructure.persistence.workspaces.models import Workspace

    workspace = Workspace.objects.filter(id=event.workspace_id).first()
    if workspace is None:
        logger.warning(
            "finding_raised_board_workspace_missing workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )
        return

    finding = FindingProvider.build_finding_store().find_by_id(event.workspace_id, event.finding_id)
    if finding is None:
        logger.warning(
            "finding_raised_board_finding_missing workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )
        return

    attrs = finding.attributes or {}
    account_id = attrs.get("account_id", "")
    check_id = attrs.get("check_id", "")
    resource_uid = attrs.get("resource_uid", "")
    region = attrs.get("region", "")
    severity = finding.severity.value

    # Reproduce the CloudPostureDetector's card shape for a board-invisible, idempotent
    # cutover (same lookup_key + labels → persist_finding_as_task dedups against the
    # existing detector card instead of creating a second one).
    lookup_key = f"cloud_posture:{account_id}:{check_id}:{resource_uid}"
    resource_label = attrs.get("resource_name") or resource_uid or "resource"
    title = f"{severity.title()}: {finding.title or check_id}"[:255]
    summary = (
        f"{finding.title or check_id} — {resource_label} "
        f"({region or 'global'}, acct {account_id or '?'}). {finding.remediation}"
    ).strip()
    payload = {
        "lookup_key": lookup_key,
        "signal": title,
        "confidence": "high",
        "check_id": check_id,
        "severity": severity,
        "account_id": account_id,
        "region": region,
        "service": attrs.get("service", ""),
        "resource_uid": resource_uid,
        "resource_type": attrs.get("resource_type", ""),
        "compliance": finding.compliance,
        "remediation": finding.remediation,
        "evidence": [f"check: {check_id}", f"resource: {resource_uid}", f"severity: {severity}"],
        "finding_id": str(finding.id),  # local copy → its finding (debt #4)
    }
    context = {
        "kind": "cloud_posture",
        "workspace_id": str(event.workspace_id),
        "finding_id": str(finding.id),
    }

    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    try:
        task_id = persist_finding_as_task(
            workspace=workspace,
            suggested_column=suggested_column,
            ai_user_id=ai_user_id,
            title=title,
            summary=summary,
            source_type=mapping["source_type"],
            agent_type="ai_teammate",  # matches the cycle's `result.agent_type or "ai_teammate"`
            detector_key=mapping["detector_key"],
            payload_data=payload,
            context=context,
            impact_score=_IMPACT.get(severity, 40),
            idempotency_key=f"lookup_key:{lookup_key}",  # matches _resolve_idempotency_key
        )
    except Exception:
        logger.exception(
            "finding_raised_board_persist_failed workspace_id=%s finding_id=%s",
            event.workspace_id,
            event.finding_id,
        )
        return

    if task_id is None:
        logger.info(
            "finding_raised_board_replay_noop workspace_id=%s finding_id=%s lookup_key=%s",
            event.workspace_id,
            event.finding_id,
            lookup_key,
        )
        return
    logger.info(
        "finding_raised_board_persisted workspace_id=%s finding_id=%s task_id=%s severity=%s",
        event.workspace_id,
        event.finding_id,
        task_id,
        severity,
    )

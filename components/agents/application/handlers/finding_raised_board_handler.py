"""Surface a raised finding onto the board as a local-copy Task (ADR 0004 Phase 3).

When a finding is raised in the SSOT, this creates/updates the Kanban card — the *local
copy* (C7), stamped with ``finding_id`` so it references its finding (debt #4). Each
finding source reproduces its legacy card shape (``source_type`` / ``agent_type`` /
idempotency ``lookup_key`` / title / evidence payload) so flipping a source onto this
path neither duplicates nor changes a card.

Per-source cutover:
- ``cloud_posture.prowler`` — GRADUATED (no flag). The ``CloudPostureDetector`` it
  replaced was retired once parity was verified; this is the sole board path.
- ``logwatch.error`` / ``logwatch.optimization`` — REVERSIBLE cutover behind
  ``feature.logwatch_board_from_findings`` (default OFF). Flag OFF → the detector cycle
  owns the board and this no-ops; flag ON (per-workspace) → the cycle stands down its
  board write (see ``finding_observed_bridge.logwatch_board_cutover_active``) and this
  drives the board, rebuilding the identical card from the finding's carried evidence.

Reads the finding's full detail through the findings context's port (C3: read-only
cross-component access via a port, never its ORM). Unmapped sources no-op.
"""

from __future__ import annotations

import logging

from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised

logger = logging.getLogger(__name__)

_IMPACT = {"critical": 90, "high": 70, "medium": 40, "low": 20, "informational": 10}

# Must equal ``finding_observed_bridge.LOGWATCH_BOARD_CUTOVER_FLAG`` — the cycle
# stand-down and this board handler gate on the SAME key (a test asserts they match).
_LOGWATCH_CUTOVER_FLAG = "feature.logwatch_board_from_findings"


def _build_cloud_posture_card(finding, event, mapping) -> dict:
    """Rebuild the retired CloudPostureDetector's card from the SSOT finding."""
    attrs = finding.attributes or {}
    account_id = attrs.get("account_id", "")
    check_id = attrs.get("check_id", "")
    resource_uid = attrs.get("resource_uid", "")
    region = attrs.get("region", "")
    severity = finding.severity.value

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
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": summary,
        "source_type": mapping["source_type"],
        "agent_type": "ai_teammate",  # matches the retired detector's attribution
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {"kind": "cloud_posture", "workspace_id": str(event.workspace_id), "finding_id": str(finding.id)},
        "impact_score": _IMPACT.get(severity, 40),
        "lookup_key": lookup_key,
    }


def _build_logwatch_card(finding, event, mapping) -> dict:
    """Rebuild the EXACT legacy cycle card for a logwatch finding from the SSOT.

    The bridge carried the full ``board_payload`` / ``board_context`` (evidence) plus
    ``agent_type`` / ``impact_score``, so the card is identical to the one the cycle
    would have written — same routing target, same triage evidence, same idempotency
    ``lookup_key`` (= the fingerprint) → a board-invisible cutover.
    """
    attrs = finding.attributes or {}
    payload = dict(attrs.get("board_payload") or {})
    payload.setdefault("lookup_key", finding.fingerprint)
    payload["finding_id"] = str(finding.id)  # local copy → its finding (debt #4)
    return {
        "title": finding.title,
        "summary": finding.description,
        "source_type": mapping["source_type"],
        "agent_type": attrs.get("agent_type") or "ai_teammate",  # the routing target
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": dict(attrs.get("board_context") or {}),
        "impact_score": int(attrs.get("impact_score") or _IMPACT.get(finding.severity.value, 40)),
        "lookup_key": finding.fingerprint,
    }


def _build_cloud_exposure_card(finding, event, mapping) -> dict:
    """Build the SOC-board card for a cloud attack-path finding (ADR 0005 phase 3).

    Born SSOT-native — there is no legacy cycle card to match. The attack-path job's
    ``FindingObserved.attributes`` carry the routing target + the path legs as evidence,
    so this card routes to the ``triage_agent`` (unlike cloud_posture, which is operator
    reading material and deliberately stays un-triaged).
    """
    attrs = finding.attributes or {}
    severity = finding.severity.value
    legs = attrs.get("legs") or []
    entry_label = attrs.get("entry_label", "") or "entry"
    target_label = attrs.get("target_label", "") or "target"
    chain = (
        " → ".join([entry_label, *[leg.get("dst_label", "") for leg in legs]])
        if legs
        else f"{entry_label} → {target_label}"
    )
    lookup_key = finding.fingerprint
    title = f"{severity.title()}: {finding.title}"[:255]
    payload = {
        "lookup_key": lookup_key,
        "signal": finding.title,
        "confidence": "high",
        "severity": severity,
        "category": attrs.get("category", ""),
        "risk_score": attrs.get("risk_score"),
        "entry": entry_label,
        "target": target_label,
        "asset_urns": attrs.get("asset_urns", []),
        "remediation": finding.remediation,
        "evidence": [
            chain,
            *[f"{leg.get('src_label', '')} -[{leg.get('relation', '')}]-> {leg.get('dst_label', '')}" for leg in legs],
        ],
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": (finding.description or chain)[:2000],
        "source_type": mapping["source_type"],
        "agent_type": attrs.get("agent_type") or "triage_agent",  # the routing target → triaged
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {"kind": "cloud_exposure", "workspace_id": str(event.workspace_id), "finding_id": str(finding.id)},
        "impact_score": int(attrs.get("impact_score") or _IMPACT.get(severity, 40)),
        "lookup_key": lookup_key,
    }


# Per finding-source board config: the legacy labels + card builder, plus the cutover
# flag (None = graduated, always surfaces). Extend as more pillars surface findings.
_SOURCE_BOARD = {
    "cloud_posture.prowler": {
        "source_type": "ai.cloud_posture",
        "detector_key": "ai_findings.cloud_posture",
        "flag": None,  # graduated (#101)
        "build": _build_cloud_posture_card,
    },
    "cloud_graph.attack_path": {
        "source_type": "ai.cloud_exposure",
        "detector_key": "ai_findings.cloud_exposure",
        "flag": None,  # born SSOT-native (graduated) — no legacy dual-write / cutover
        "build": _build_cloud_exposure_card,
    },
    "logwatch.error": {
        "source_type": "ai.log_watch",
        "detector_key": "logwatch.error",
        "flag": _LOGWATCH_CUTOVER_FLAG,
        "build": _build_logwatch_card,
    },
    "logwatch.optimization": {
        "source_type": "ai.log_optimization",
        "detector_key": "logwatch.optimization",
        "flag": _LOGWATCH_CUTOVER_FLAG,
        "build": _build_logwatch_card,
    },
}


def _cutover_enabled(flag: str, workspace_id) -> bool:
    """Fail-closed flag check: any error → False → the legacy cycle path owns the board."""
    try:
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        return bool(get_feature_flags_provider().is_feature_enabled(flag, workspace_id=workspace_id))
    except Exception:
        logger.exception("finding_raised_board_flag_check_failed workspace_id=%s flag=%s", workspace_id, flag)
        return False


@subscribes_to(FindingRaised)
def handle_finding_raised_board(event: FindingRaised) -> None:
    mapping = _SOURCE_BOARD.get(event.source)
    if mapping is None:
        return  # this source is not board-surfaced via the SSOT path yet

    flag = mapping.get("flag")
    if flag and not _cutover_enabled(flag, event.workspace_id):
        return  # reversible cutover OFF → the detector cycle owns this source's board

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

    card = mapping["build"](finding, event, mapping)
    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    try:
        task_id = persist_finding_as_task(
            workspace=workspace,
            suggested_column=suggested_column,
            ai_user_id=ai_user_id,
            title=card["title"],
            summary=card["summary"],
            source_type=card["source_type"],
            agent_type=card["agent_type"],
            detector_key=card["detector_key"],
            payload_data=card["payload"],
            context=card["context"],
            impact_score=card["impact_score"],
            idempotency_key=f"lookup_key:{card['lookup_key']}",  # matches _resolve_idempotency_key
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
            "finding_raised_board_replay_noop workspace_id=%s finding_id=%s source=%s lookup_key=%s",
            event.workspace_id,
            event.finding_id,
            event.source,
            card["lookup_key"],
        )
        return
    logger.info(
        "finding_raised_board_persisted workspace_id=%s finding_id=%s task_id=%s source=%s severity=%s",
        event.workspace_id,
        event.finding_id,
        task_id,
        event.source,
        finding.severity.value,
    )

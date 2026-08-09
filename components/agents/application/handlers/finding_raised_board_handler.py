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
        # The routing target. The bridge normally carries it from the detector; the
        # FALLBACK is the source's own specialist, never the orchestrator — a
        # routable card stamped ``ai_teammate`` is skipped by the router and the
        # finding is silently never triaged (the ``ai.code_security`` strand, found
        # by ``test_every_routable_board_source_names_a_real_specialist``).
        "agent_type": attrs.get("agent_type") or mapping.get("default_agent_type") or "ai_teammate",
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
        "mitre": attrs.get("mitre", []),  # ATT&CK technique set for the finding (chip), kill-chain order
        "attack_flow": attrs.get("attack_flow", []),  # per-hop ATT&CK render: entry → each mapped leg
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


def _build_container_security_card(finding, event, mapping) -> dict:
    """Build the SOC-board card for a Trivy container-image vulnerability finding.

    Operator-reading material like cloud_posture (``agent_type`` = ``ai_teammate``): this
    slice surfaces the CVE on the board from the SSOT; routing it to a CVE-triage
    specialist (an "upgrade the package" advisor) is the next slice.
    """
    attrs = finding.attributes or {}
    severity = finding.severity.value
    vuln_id = attrs.get("vulnerability_id", "")
    pkg = attrs.get("pkg_name", "")
    installed = attrs.get("installed_version", "")
    fixed = attrs.get("fixed_version", "")
    lookup_key = finding.fingerprint
    label = f"{vuln_id or finding.title} in {pkg}" if pkg else (finding.title or vuln_id)
    title = f"{severity.title()}: {label}"[:255]
    summary = (f"{pkg} {installed} — {vuln_id}. {finding.remediation}." if pkg else finding.description).strip()
    payload = {
        "lookup_key": lookup_key,
        "signal": finding.title,
        "confidence": "high",
        "severity": severity,
        "vulnerability_id": vuln_id,
        "pkg_name": pkg,
        "installed_version": installed,
        "fixed_version": fixed,
        "primary_url": attrs.get("primary_url", ""),
        "target": attrs.get("target", ""),
        "remediation": finding.remediation,
        "evidence": [f"{vuln_id}: {pkg} {installed}" + (f" (fixed in {fixed})" if fixed else " (no fix available)")],
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": (summary or finding.description)[:2000],
        "source_type": mapping["source_type"],
        "agent_type": "triage_agent",  # routed to the CVE-triage specialist (slice 2)
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {
            "kind": "container_security",
            "workspace_id": str(event.workspace_id),
            "finding_id": str(finding.id),
        },
        "impact_score": _IMPACT.get(severity, 40),
        "lookup_key": lookup_key,
    }


def _build_code_security_card(finding, event, mapping) -> dict:
    """Build the SOC-board card for an Opengrep SAST finding (ADR 0019 P1/P2).

    Born SSOT-native. Card copy leads with the rule + ``path:line`` (the SAST
    analogue of the CSPM check + ARN). P2: routed to the ``code_security_agent``
    specialist, whose ``triage_code_finding`` tool grounds a fix suggestion and
    drives the draft-PR loop — the ROUTABLE entry ships in the same change as
    the tool ("routable without a tool is a silent no-op").
    """
    attrs = finding.attributes or {}
    severity = finding.severity.value
    rule_id = attrs.get("rule_id", "")
    path = attrs.get("path", "")
    start_line = attrs.get("start_line", 0)
    repo = attrs.get("repo", "")
    location = f"{path}:{start_line}" if path else "unknown location"
    rule_label = rule_id.rsplit(".", 1)[-1] if rule_id else "finding"
    lookup_key = finding.fingerprint
    title = f"{severity.title()}: {rule_label} — {location}"[:255]
    summary = (f"{finding.title} {repo} {location}. {finding.remediation}").strip()
    payload = {
        "lookup_key": lookup_key,
        "signal": finding.title,
        "confidence": attrs.get("confidence", "high"),
        "severity": severity,
        "rule_id": rule_id,
        "rule_source": attrs.get("rule_source", ""),
        "repo": repo,
        "commit_sha": attrs.get("commit_sha", ""),
        "path": path,
        "start_line": start_line,
        "end_line": attrs.get("end_line", 0),
        "cwe": attrs.get("cwe", []),
        "language": attrs.get("language", ""),
        # The matched region (already masked upstream for secret-class rules,
        # ADR 0019 D8) — the triage advisor + verifier ground on it and the HUD
        # callout renders it through the sanitized HudCodeBlock primitive.
        "snippet": attrs.get("snippet", ""),
        "message": finding.title,
        "remediation": finding.remediation,
        "evidence": [
            f"rule: {rule_id}",
            f"location: {repo} {location} @ {str(attrs.get('commit_sha', ''))[:12]}",
            f"severity: {severity}",
        ],
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": (summary or finding.description)[:2000],
        "source_type": mapping["source_type"],
        "agent_type": "code_security_agent",  # routed to the SAST specialist (P2)
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {
            "kind": "code_security",
            "workspace_id": str(event.workspace_id),
            "finding_id": str(finding.id),
        },
        "impact_score": _IMPACT.get(severity, 40),
        "lookup_key": lookup_key,
    }


def _build_vercel_posture_card(finding, event, mapping) -> dict:
    """Build the SOC-board card for a Vercel posture finding (ADR 0021 D4).

    Born SSOT-native. Card copy leads with the check + the project (the Vercel
    analogue of the CSPM check + ARN; the team id is the account-id analog).
    Operator-reading material like AWS cloud_posture (``agent_type`` =
    ``ai_teammate``): routing to a triage specialist ships together with its tool
    in a later slice — "routable without a tool is a silent no-op".

    A MANUAL check (Prowler could not verify it under this token — e.g. the 5
    firewall checks with no accessible firewall endpoint, ADR 0021 R4) surfaces
    HONESTLY: it keeps its card, is labelled MANUAL, and drops to medium
    confidence — it never renders as a PASS and never vanishes.
    """
    attrs = finding.attributes or {}
    team_id = attrs.get("team_id") or attrs.get("account_id", "")
    check_id = attrs.get("check_id", "")
    resource_uid = attrs.get("resource_uid", "")
    check_status = attrs.get("check_status", "")
    is_manual = check_status == "manual"
    severity = finding.severity.value

    lookup_key = finding.fingerprint
    resource_label = attrs.get("resource_name") or resource_uid or "resource"
    title = f"{severity.title()}: {finding.title or check_id}"[:255]
    manual_note = "MANUAL — could not be verified with the connected token. " if is_manual else ""
    summary = (
        f"{manual_note}{finding.title or check_id} — {resource_label} (team {team_id or '?'}). {finding.remediation}"
    ).strip()
    payload = {
        "lookup_key": lookup_key,
        "signal": title,
        "confidence": "medium" if is_manual else "high",
        "check_id": check_id,
        "check_status": check_status,
        "severity": severity,
        "team_id": team_id,
        "service": attrs.get("service", ""),
        "resource_uid": resource_uid,
        "resource_type": attrs.get("resource_type", ""),
        "resource_name": attrs.get("resource_name", ""),
        "compliance": finding.compliance,
        "remediation": finding.remediation,
        "evidence": [
            f"check: {check_id}",
            f"resource: {resource_uid}",
            f"severity: {severity}",
            f"status: {check_status or 'fail'}",
        ],
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": summary[:2000],
        "source_type": mapping["source_type"],
        "agent_type": "ai_teammate",  # operator reading material — no triage tool yet (deliberate)
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {
            "kind": "vercel_posture",
            "workspace_id": str(event.workspace_id),
            "finding_id": str(finding.id),
        },
        "impact_score": _IMPACT.get(severity, 40),
        "lookup_key": lookup_key,
    }


def _build_planted_instructions_card(finding, event, mapping) -> dict:
    """Board card for AI-targeted instructions planted in repository content.

    The novel signal the SAST pillar raises when the remediation advisor's
    consent-checked file read trips the injection heuristic: someone wrote text
    into the customer's codebase intended to be READ AS INSTRUCTIONS by an AI
    assistant. Operator-reading material (``agent_type`` = ``ai_teammate``) — the
    response is a human investigation (`git log -p` on the file), not an
    auto-generated patch, so there is deliberately no triage tool and no
    ROUTABLE entry for this source.

    The suspicious TEXT is never carried onto the card (ADR 0019 D8 discipline
    generalized): reproducing a planted instruction into the board, the
    notifications and every projection would spread the payload.
    """
    attrs = finding.attributes or {}
    severity = finding.severity.value
    repo = attrs.get("repo", "")
    path = attrs.get("path", "")
    lookup_key = finding.fingerprint
    title = f"{severity.title()}: AI-targeted instructions in {path or 'repository content'}"[:255]
    payload = {
        "lookup_key": lookup_key,
        "signal": finding.title,
        "confidence": "medium",  # heuristic match — a human confirms
        "severity": severity,
        "repo": repo,
        "path": path,
        "commit_sha": attrs.get("commit_sha", ""),
        "category": attrs.get("category", "planted_ai_instructions"),
        "triggering_rule_id": attrs.get("triggering_rule_id", ""),
        "remediation": finding.remediation,
        "evidence": [
            f"file: {repo} {path}",
            "detector: prompt-injection heuristic over repository content",
            "note: the matched text is deliberately not reproduced here",
        ],
        "finding_id": str(finding.id),
    }
    return {
        "title": title,
        "summary": (finding.description or title)[:2000],
        "source_type": mapping["source_type"],
        "agent_type": "ai_teammate",  # operator investigation, not an auto-fix
        "detector_key": mapping["detector_key"],
        "payload": payload,
        "context": {
            "kind": "planted_instructions",
            "workspace_id": str(event.workspace_id),
            "finding_id": str(finding.id),
        },
        "impact_score": _IMPACT.get(severity, 40),
        "lookup_key": lookup_key,
    }


# Per finding-source board config: the legacy labels + card builder, plus the cutover
# flag (None = graduated, always surfaces). Extend as more pillars surface findings.
# ``min_severity`` (optional) is the board floor (ADR 0019 D4 layer 2): findings
# below it stay SSOT-only (HUD findings panel) and never become cards.
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
    "container_security.trivy": {
        "source_type": "ai.container_security",
        "detector_key": "ai_findings.container_security",
        "flag": None,  # graduated (operator-reading; CVE triage routing is the next slice)
        "build": _build_container_security_card,
    },
    "code_security.opengrep": {
        "source_type": "ai.code_security",
        "detector_key": "ai_findings.code_security",
        "flag": None,  # born SSOT-native; the pillar itself is dark behind feature.code_security
        "min_severity": "high",  # board floor (ADR 0019 D4/OQ4 default: high+critical)
        "build": _build_code_security_card,
    },
    "cloud_posture.prowler.vercel": {
        "source_type": "ai.vercel_posture",
        "detector_key": "ai_findings.vercel_posture",
        "flag": None,  # born SSOT-native; the pillar itself is dark behind feature.vercel_posture
        "min_severity": "high",  # board floor (ADR 0021 D4 — domain/DNS hygiene stays SSOT-only)
        "build": _build_vercel_posture_card,
    },
    "code_security.planted_instructions": {
        "source_type": "ai.planted_instructions",
        "detector_key": "ai_findings.planted_instructions",
        "flag": None,  # born SSOT-native; rides the code_security pillar's own flag
        "build": _build_planted_instructions_card,
    },
    "logwatch.error": {
        "source_type": "ai.log_watch",
        "detector_key": "logwatch.error",
        "flag": _LOGWATCH_CUTOVER_FLAG,
        "default_agent_type": "triage_agent",  # routable → must fall back to a REAL specialist
        "build": _build_logwatch_card,
    },
    "logwatch.optimization": {
        "source_type": "ai.log_optimization",
        "detector_key": "logwatch.optimization",
        "flag": _LOGWATCH_CUTOVER_FLAG,
        "default_agent_type": "optimization_agent",
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
    from components.agents.application.providers.ai_provider import AIProvider
    from components.agents.infrastructure.services.agents_board_service import SUGGESTED
    from components.agents.infrastructure.services.finding_dispatch_service import (
        request_specialist_dispatch,
    )
    from components.findings.application.providers.finding_provider import FindingProvider

    workspace = AIProvider.build_workspace_query().get_by_id(event.workspace_id)
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

    floor = mapping.get("min_severity")
    if floor and _IMPACT.get(finding.severity.value, 0) < _IMPACT.get(floor, 0):
        logger.info(
            "finding_raised_board_below_floor workspace_id=%s finding_id=%s source=%s severity=%s floor=%s",
            event.workspace_id,
            event.finding_id,
            event.source,
            finding.severity.value,
            floor,
        )
        return  # SSOT-only: visible in the findings panel, no board card (ADR 0019 D4)

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

    # Fire the owning specialist NOW rather than leaving the finding to wait for the
    # next 5-minutely cadence tick. THIS is the honest choke point for "the moment
    # the scan happens": ``ScanCompleted`` reads like the natural hook but is
    # published as its own Celery task alongside the ``FindingObserved`` batch, two
    # async hops BEFORE any card exists — a dispatch hung off it would run against an
    # empty backlog and burn the lease. Here, the precondition genuinely holds: a
    # routable card exists. It is also source-agnostic (log-watch findings never come
    # from a scan at all).
    #
    # Bounded by construction: this is O(1) per finding (one cache op, no query), and
    # the shared per-(workspace, specialist) lease collapses a 500-finding scan into
    # ONE dispatch carrying all of them. The cadence remains the backstop.
    request_specialist_dispatch(
        event.workspace_id,
        card["agent_type"],
        source_type=card["source_type"],
        trigger="finding_raised",
    )

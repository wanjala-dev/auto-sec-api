"""Output DTO for the findings read API — maps a ranked finding to a JSON-safe dict."""

from __future__ import annotations

from components.findings.application.queries.finding_triage_state_query import FindingTriageStateView
from components.findings.application.queries.list_findings_query import (
    FindingPage,
    FindingRiskView,
    RankedFinding,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.shared_kernel.domain.tagging import TagRef


class FindingResource:
    @staticmethod
    def tag_ref_dict(ref: TagRef) -> dict:
        """One tag chip (ADR 0015): the id (durable identity), slug (filter handle),
        and display fields."""
        return {"id": str(ref.id), "slug": ref.slug, "name": ref.name, "color": ref.color}

    @staticmethod
    def _finding_dict(e: FindingEntity) -> dict:
        return {
            "id": str(e.id),
            "source": e.source,
            "fingerprint": e.fingerprint,
            "asset_urn": e.asset_urn,
            "severity": e.severity.value,
            "status": e.status.value,
            "is_open": e.is_open,
            "title": e.title,
            "description": e.description,
            "remediation": e.remediation,
            "compliance": e.compliance,
            "attributes": e.attributes,
            "status_reason": e.status_reason,
            "suppress_expires_at": e.suppress_expires_at.isoformat() if e.suppress_expires_at else None,
            "tags": [FindingResource.tag_ref_dict(ref) for ref in e.tags],
            "first_seen_at": e.first_seen_at.isoformat() if e.first_seen_at else None,
            "last_seen_at": e.last_seen_at.isoformat() if e.last_seen_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }

    @staticmethod
    def _risk_dict(risk: FindingRiskView | None) -> dict | None:
        """The contextual-risk block (ADR 0013): score + band + EPSS%/KEV/exposure badges +
        the explainable factor breakdown. None until the recompute job has scored it."""
        if risk is None:
            return None
        return {
            "score": risk.score,
            "band": risk.band,
            "epss": risk.epss,
            "epss_percentile": risk.epss_percentile,
            "in_kev": risk.in_kev,
            "exposure": risk.exposure,
            "exposure_unknown": risk.exposure_unknown,
            "factors": risk.factors,
        }

    @staticmethod
    def _triage_dict(triage: FindingTriageStateView | None) -> dict | None:
        """Where this finding sits between "detected" and "fix proposed".

        The HUD renders this on every finding so there is never an unexplained gap:
        QUEUED names the next cadence pass, DRAFTING says a specialist is working
        now, FIX READY carries the verified suggestion + the draft-PR affordance,
        FIX UNVERIFIED carries the suggestion + the named evidence gap + the
        [UNVERIFIED]-labeled draft PR, NO FIX carries WHY plus the retry
        affordance, and NOT ROUTED says plainly that this kind of finding has no
        automated fix path.
        """
        if triage is None:
            return None
        return {
            "state": triage.state,
            "specialist": triage.specialist,
            "next_triage_at": triage.next_triage_at.isoformat() if triage.next_triage_at else None,
            "reason": triage.reason,
            "task_id": triage.task_id,
            "triaged_at": triage.triaged_at,
            "suggested_fix": triage.suggested_fix,
            "confidence": triage.confidence,
            "verification": triage.verification,
            "verification_gap": triage.verification_gap,
            # WHERE the fix lands (repo → draft PR; image → fix snippet; cloud/
            # service → guidance). The HUD keys the affordance + chip copy off it.
            "remediation_target": triage.remediation_target,
            "fix_snippet": triage.fix_snippet,
            "fix_snippet_language": triage.fix_snippet_language,
            "draft_pr": triage.draft_pr,
            "blocked_reason": triage.blocked_reason,
            "can_draft_fix": triage.can_draft_fix,
            # Task #145: the outcome contract. ``design_change`` means the
            # artifact is the brief below, and can_draft_fix is always False.
            "outcome": triage.outcome,
            "remediation_brief": triage.remediation_brief,
        }

    @staticmethod
    def from_ranked(row: RankedFinding) -> dict:
        data = FindingResource._finding_dict(row.finding)
        data["risk"] = FindingResource._risk_dict(row.risk)
        data["triage"] = FindingResource._triage_dict(row.triage)
        return data

    @staticmethod
    def page(page: FindingPage) -> dict:
        return {
            "items": [FindingResource.from_ranked(row) for row in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        }

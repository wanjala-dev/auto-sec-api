"""Triage agent tools — the consumer half of the SOC log pipeline.

The ``LogWatchErrorDetector`` files evidence-bearing findings (pending triage)
via the ``AIActionCreated`` path. These tools let the triage agent — invoked as
a worker through the orchestrator/deep pipeline from the detector cycle — pick
up each pending finding, look at the error, propose a grounded fix, comment it
on the card, and move the card into the In Progress lane (ADR 0030 D2 — the AI state is the
metadata.triage chip, not a bespoke lane), recording a full trace.

The board choreography + concurrency guard + provenance live in
``_finding_processing`` (shared with the optimization agent). These functions
supply only the triage-specific bits: the fix advisor, the comment text, and
which payload fields the suggestion fills. Everything mutates existing board
tasks (comment / column / metadata) — all reversible, so ``triage_finding`` is
a ``reversible_write`` tier and an autonomous run may execute it.
"""

from __future__ import annotations

import json
import logging

from components.agents.infrastructure.adapters.langchain.tools import _finding_processing as fp

logger = logging.getLogger(__name__)

_LOG_WATCH_SOURCE = "ai.log_watch"
_CLOUD_EXPOSURE_SOURCE = "ai.cloud_exposure"
_CONTAINER_SECURITY_SOURCE = "ai.container_security"
ACTING_COLUMN_TITLE = fp.ACTING_COLUMN_TITLE


def _pending_findings_qs(workspace_id):
    return fp.pending_findings_qs(workspace_id, _LOG_WATCH_SOURCE)


def list_pending_log_findings(agent, input_str: str = "") -> str:
    """READ — list log-watch findings on the board not yet triaged."""
    pending = _pending_findings_qs(agent.workspace_id)
    if not pending:
        return "No pending log-watch findings to triage."
    rows = []
    for t in pending[:20]:
        payload = (t.metadata or {}).get("payload") or {}
        rows.append(
            {
                "task_id": str(t.id),
                "title": t.title[:120],
                "service": payload.get("service") or "",
                "level": payload.get("level") or "",
                "signal": payload.get("signal") or "",
            }
        )
    return json.dumps(rows)


def triage_finding(agent, input_str: str) -> str:
    """REVERSIBLE_WRITE — triage one pending finding: suggest a fix, comment it,
    move the card to the In Progress lane, and record the trace + provenance.
    """
    from components.integrations.application.log_fix_advisor_service import LogFixAdvisor

    def advise(payload, feedback=""):
        service = payload.get("service") or "unknown"
        level = payload.get("level") or "ERROR"
        message = (payload.get("message") or payload.get("signal") or "")[:1600]
        # ADR 0012 P4: ground the suggestion in the workspace's vetted prior fixes
        # for this finding class. Grounding never authorizes — the grounded verifier
        # (verify_suggestion) still runs on the result in process_pending_finding (D2).
        return LogFixAdvisor().suggest(
            service=service,
            level=level,
            message=message,
            feedback=feedback,
            workspace_id=str(agent.workspace_id),
            source_type=_LOG_WATCH_SOURCE,
        )

    def suggestion_text(suggestion):
        # The full grounding surface the verifier checks against the error evidence.
        return f"{suggestion.likely_cause} {suggestion.suggested_fix}"

    def build_comment(suggestion):
        if suggestion is None:
            return (
                "🔎 Triage agent reviewed this error but could not derive a confident fix "
                "from the log line alone — needs a human eye."
            )
        return (
            f"🔎 Triage agent looked at this error.\n\n"
            f"Likely cause: {suggestion.likely_cause}\n\n"
            f"Suggested fix: {suggestion.suggested_fix}\n\n"
            f"Confidence: {suggestion.confidence}."
        )

    def apply_payload(payload, suggestion):
        payload["probable_cause"] = suggestion.likely_cause
        payload["suggested_fix"] = suggestion.suggested_fix
        payload["confidence"] = suggestion.confidence

    def describe_action(suggestion):
        if suggestion is None:
            return "reviewed; no confident fix from the log line"
        return f"suggested a fix ({suggestion.confidence} confidence)"

    return fp.process_pending_finding(
        agent,
        input_str,
        source_type=_LOG_WATCH_SOURCE,
        column_title=ACTING_COLUMN_TITLE,
        acting_agent="triage_agent",
        advise=advise,
        build_comment=build_comment,
        apply_payload=apply_payload,
        describe_action=describe_action,
        suggestion_text=suggestion_text,
    )


def list_pending_cloud_exposure_findings(agent, input_str: str = "") -> str:
    """READ — list cloud attack-path findings on the board not yet triaged."""
    pending = fp.pending_findings_qs(agent.workspace_id, _CLOUD_EXPOSURE_SOURCE)
    if not pending:
        return "No pending cloud-exposure (attack-path) findings to triage."
    rows = []
    for t in pending[:20]:
        payload = (t.metadata or {}).get("payload") or {}
        rows.append(
            {
                "task_id": str(t.id),
                "title": t.title[:120],
                "category": payload.get("category") or "",
                "entry": payload.get("entry") or "",
                "target": payload.get("target") or "",
                "risk_score": payload.get("risk_score"),
            }
        )
    return json.dumps(rows)


def triage_cloud_exposure(agent, input_str: str) -> str:
    """REVERSIBLE_WRITE — triage one pending cloud attack-path finding: recommend how to
    break the toxic chain, comment it, move the card to In Progress, and record the trace.

    Same board choreography + concurrency guard + grounded-verification loop as
    ``triage_finding`` (via ``process_pending_finding``); it supplies only the
    cloud-exposure-specific advisor (``AttackPathRemediationAdvisor``), comment, and
    payload fields. The suggestion is grounded in the path's own evidence — it names the
    entry and the crown-jewel target — so the ``finding_verifier`` / RubricMiddleware
    grader grades it against the attack-path chain, not against log-error symbols.
    """
    from components.cloud_graph.domain.services.attack_path_remediation_advisor import (
        AttackPathRemediationAdvisor,
    )

    advisor = AttackPathRemediationAdvisor()

    def advise(payload, feedback=""):
        return advisor.suggest(
            category=str(payload.get("category") or ""),
            entry_label=str(payload.get("entry") or ""),
            target_label=str(payload.get("target") or ""),
            feedback=feedback,
        )

    def suggestion_text(suggestion):
        # The grounding surface the verifier checks against the attack-path evidence
        # (it names the entry + target, which are the path's checkable specifics).
        return f"{suggestion.likely_cause} {suggestion.suggested_fix}"

    def build_comment(suggestion):
        if suggestion is None:
            return (
                "🛡 Triage agent reviewed this attack path but could not derive a confident "
                "remediation from the finding alone — needs a human eye."
            )
        return (
            f"🛡 Triage agent analysed this attack path.\n\n"
            f"Why it is toxic: {suggestion.likely_cause}\n\n"
            f"How to break it: {suggestion.suggested_fix}\n\n"
            f"Confidence: {suggestion.confidence}."
        )

    def apply_payload(payload, suggestion):
        payload["probable_cause"] = suggestion.likely_cause
        payload["suggested_fix"] = suggestion.suggested_fix
        payload["confidence"] = suggestion.confidence

    def describe_action(suggestion):
        if suggestion is None:
            return "reviewed; no confident remediation from the finding"
        return f"recommended breaking the attack path ({suggestion.confidence} confidence)"

    return fp.process_pending_finding(
        agent,
        input_str,
        source_type=_CLOUD_EXPOSURE_SOURCE,
        column_title=ACTING_COLUMN_TITLE,
        acting_agent="triage_agent",
        advise=advise,
        build_comment=build_comment,
        apply_payload=apply_payload,
        describe_action=describe_action,
        suggestion_text=suggestion_text,
    )


def list_pending_container_vuln_findings(agent, input_str: str = "") -> str:
    """READ — list Trivy container-image CVE findings on the board not yet triaged."""
    pending = fp.pending_findings_qs(agent.workspace_id, _CONTAINER_SECURITY_SOURCE)
    if not pending:
        return "No pending container-vulnerability findings to triage."
    rows = []
    for t in pending[:20]:
        payload = (t.metadata or {}).get("payload") or {}
        rows.append(
            {
                "task_id": str(t.id),
                "title": t.title[:120],
                "vulnerability_id": payload.get("vulnerability_id") or "",
                "pkg_name": payload.get("pkg_name") or "",
                "fixed_version": payload.get("fixed_version") or "",
            }
        )
    return json.dumps(rows)


def triage_container_vuln(agent, input_str: str) -> str:
    """REVERSIBLE_WRITE — triage one pending container-image CVE finding: recommend the
    package upgrade (or a mitigation when no fix exists), comment it, move the card to
    In Progress, and record the trace.

    Same board choreography + concurrency guard + grounded-verification loop as
    ``triage_finding`` (via ``process_pending_finding``); it supplies only the CVE-specific
    advisor (``ContainerVulnRemediationAdvisor``), comment, and payload fields. The
    suggestion is grounded in the finding's own evidence — it names the package + the fixed
    version — so the ``finding_verifier`` / RubricMiddleware grader grades it against the CVE.
    """
    from components.container_security.domain.services.container_vuln_remediation_advisor import (
        ContainerVulnRemediationAdvisor,
    )

    advisor = ContainerVulnRemediationAdvisor()

    def advise(payload, feedback=""):
        return advisor.suggest(
            vulnerability_id=str(payload.get("vulnerability_id") or ""),
            pkg_name=str(payload.get("pkg_name") or ""),
            installed_version=str(payload.get("installed_version") or ""),
            fixed_version=str(payload.get("fixed_version") or ""),
            target=str(payload.get("target") or ""),
            feedback=feedback,
        )

    def suggestion_text(suggestion):
        # The grounding surface the verifier checks against the CVE evidence (it names the
        # package + fixed version, the finding's checkable specifics).
        return f"{suggestion.likely_cause} {suggestion.suggested_fix}"

    def build_comment(suggestion):
        if suggestion is None:
            return (
                "📦 Triage agent reviewed this vulnerability but could not derive a confident "
                "remediation from the finding alone — needs a human eye."
            )
        comment = (
            f"📦 Triage agent analysed this container vulnerability.\n\n"
            f"Why it is a risk: {suggestion.likely_cause}\n\n"
            f"How to fix it: {suggestion.suggested_fix}\n\n"
        )
        if (suggestion.fix_snippet or "").strip():
            # The image-target artifact: no repo to PR against, so the fix ships
            # as copy-pasteable Dockerfile/package guidance on the card.
            comment += f"Fix snippet:\n```dockerfile\n{suggestion.fix_snippet}\n```\n\n"
        return comment + f"Confidence: {suggestion.confidence}."

    def apply_payload(payload, suggestion):
        payload["probable_cause"] = suggestion.likely_cause
        payload["suggested_fix"] = suggestion.suggested_fix
        payload["confidence"] = suggestion.confidence
        # The FIX SNIPPET is the artifact for an image-target finding (no linked
        # repo → no PR); the HUD renders it through the sanitized code block.
        payload["fix_snippet"] = suggestion.fix_snippet
        payload["fix_snippet_language"] = suggestion.fix_snippet_language

    def describe_action(suggestion):
        if suggestion is None:
            return "reviewed; no confident remediation from the finding"
        return f"recommended a package upgrade ({suggestion.confidence} confidence)"

    return fp.process_pending_finding(
        agent,
        input_str,
        source_type=_CONTAINER_SECURITY_SOURCE,
        column_title=ACTING_COLUMN_TITLE,
        acting_agent="triage_agent",
        advise=advise,
        build_comment=build_comment,
        apply_payload=apply_payload,
        describe_action=describe_action,
        suggestion_text=suggestion_text,
    )


def open_draft_pr(agent, input_str: str) -> str:
    """IRREVERSIBLE — open a DRAFT GitHub PR for one triaged finding.

    Thin delegation to the integrations use case (the single choke point that
    enforces EVERY precondition: installed connection, repo allowlist, finding
    triaged, capability enabled — and that LABELS an ungrounded/low-confidence
    fix's PR [UNVERIFIED] instead of withholding it). The risk gate denies
    autonomous runs before this body executes; ``performed_by`` is therefore
    the approving human principal driving this run.
    """
    from components.integrations.application.providers.vcs_provider import get_open_draft_pr_use_case
    from components.integrations.application.use_cases.open_draft_pr_use_case import (
        APPROVAL_OPERATOR,
        DraftPrPreconditionError,
    )

    raw = (input_str or "").strip()
    try:
        data = json.loads(raw) if raw.startswith("{") else {"task_id": raw}
    except (ValueError, TypeError):
        data = {"task_id": raw}
    task_id = (data.get("task_id") or "").strip()
    if not task_id:
        return "task_id is required to open a draft PR."

    from components.integrations.application.ports.vcs_port import VcsApiError

    try:
        result = get_open_draft_pr_use_case().execute(
            workspace_id=str(agent.workspace_id),
            task_id=task_id,
            performed_by=str(agent.user_id),
            repo=(data.get("repo") or "").strip() or None,
            # ``irreversible`` tier: the risk gate denied this call unless a human
            # approved the run, so the PR may say an operator approved the patch.
            approval=APPROVAL_OPERATOR,
        )
    except DraftPrPreconditionError as exc:
        return f"Cannot open a draft PR ({exc.reason}): {exc}"
    except VcsApiError as exc:
        logger.exception("open_draft_pr vcs api error task_id=%s", task_id)
        return f"VCS API error while opening the draft PR: {exc}"

    if not result.created:
        return f"A draft PR already exists for this finding: {result.url}"
    if getattr(result, "verification", "") == "unverified":
        return (
            f"Opened draft PR {result.url} (repo {result.repo}, branch {result.branch}) "
            f"labeled UNVERIFIED — {result.verification_gap or 'the fix could not be grounded'}; "
            "a human must review it carefully before merging."
        )
    return f"Opened draft PR {result.url} (repo {result.repo}, branch {result.branch})."

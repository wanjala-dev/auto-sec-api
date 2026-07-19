"""Triage agent tools — the consumer half of the SOC log pipeline.

The ``LogWatchErrorDetector`` files evidence-bearing findings (pending triage)
via the ``AIActionCreated`` path. These tools let the triage agent — invoked as
a worker through the orchestrator/deep pipeline from the detector cycle — pick
up each pending finding, look at the error, propose a grounded fix, comment it
on the card, and move the card into the Triage column, recording a full trace.

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
TRIAGE_COLUMN_TITLE = "Triage"


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
    move the card to the Triage column, and record the trace + provenance.
    """
    from components.integrations.application.log_fix_advisor_service import LogFixAdvisor

    def advise(payload, feedback=""):
        service = payload.get("service") or "unknown"
        level = payload.get("level") or "ERROR"
        message = (payload.get("message") or payload.get("signal") or "")[:1600]
        return LogFixAdvisor().suggest(service=service, level=level, message=message, feedback=feedback)

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
        column_title=TRIAGE_COLUMN_TITLE,
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
    triaged + not needs_human, capability enabled). The risk gate denies
    autonomous runs before this body executes; ``performed_by`` is therefore
    the approving human principal driving this run.
    """
    from components.integrations.application.providers.github_pr_provider import get_open_draft_pr_use_case
    from components.integrations.application.use_cases.open_draft_pr_use_case import DraftPrPreconditionError

    raw = (input_str or "").strip()
    try:
        data = json.loads(raw) if raw.startswith("{") else {"task_id": raw}
    except (ValueError, TypeError):
        data = {"task_id": raw}
    task_id = (data.get("task_id") or "").strip()
    if not task_id:
        return "task_id is required to open a draft PR."

    from components.integrations.application.ports.github_pr_port import GitHubApiError

    try:
        result = get_open_draft_pr_use_case().execute(
            workspace_id=str(agent.workspace_id),
            task_id=task_id,
            performed_by=str(agent.user_id),
            repo=(data.get("repo") or "").strip() or None,
        )
    except DraftPrPreconditionError as exc:
        return f"Cannot open a draft PR ({exc.reason}): {exc}"
    except GitHubApiError as exc:
        logger.exception("open_draft_pr github api error task_id=%s", task_id)
        return f"GitHub API error while opening the draft PR: {exc}"

    if not result.created:
        return f"A draft PR already exists for this finding: {result.url}"
    return f"Opened draft PR {result.url} (repo {result.repo}, branch {result.branch})."

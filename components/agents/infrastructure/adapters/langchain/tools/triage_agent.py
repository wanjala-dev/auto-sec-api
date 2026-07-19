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

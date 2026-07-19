"""Optimization agent tools — the consumer half of the log-optimization pipeline.

The ``LogOptimizationDetector`` files evidence-bearing pattern findings (an
over-scheduled beat task, health-check noise, a volume hotspot) via the
``AIActionCreated`` path, targeting this specialist. These tools let the
optimization agent — invoked as a worker through the orchestrator/deep pipeline
from the detector cycle — pick up each pending pattern, turn its measured
frequency into a concrete tuning recommendation, comment it on the card, and
move the card into the Optimize column, recording a full trace + provenance.

The board choreography + concurrency guard + provenance are shared with the
triage agent (``_finding_processing``); this module supplies only the
optimization-specific advisor, comment, and payload fields. All mutations are
reversible (comment / column / metadata) → ``reversible_write`` tier. A future
"apply the schedule change" tool would be ``irreversible`` and gated (SEE-203).
"""

from __future__ import annotations

import json
import logging

from components.agents.infrastructure.adapters.langchain.tools import _finding_processing as fp

logger = logging.getLogger(__name__)

_LOG_OPTIMIZATION_SOURCE = "ai.log_optimization"
OPTIMIZE_COLUMN_TITLE = "Optimize"


def _pending_findings_qs(workspace_id):
    return fp.pending_findings_qs(workspace_id, _LOG_OPTIMIZATION_SOURCE)


def list_pending_optimizations(agent, input_str: str = "") -> str:
    """READ — list log-optimization findings on the board not yet handled."""
    pending = _pending_findings_qs(agent.workspace_id)
    if not pending:
        return "No pending log-optimization findings."
    rows = []
    for t in pending[:20]:
        payload = (t.metadata or {}).get("payload") or {}
        freq = payload.get("frequency") or {}
        rows.append(
            {
                "task_id": str(t.id),
                "title": t.title[:120],
                "service": payload.get("service") or "",
                "kind": payload.get("kind") or "",
                "subject": payload.get("subject") or "",
                "last_window": freq.get("last_window"),
                "signal": payload.get("signal") or "",
            }
        )
    return json.dumps(rows)


def advise_optimization(agent, input_str: str) -> str:
    """REVERSIBLE_WRITE — advise one pending optimization: turn the measured
    pattern into a concrete tuning recommendation, comment it, move the card to
    the Optimize column, and record the trace + provenance.
    """
    from components.integrations.application.log_optimization_advisor_service import LogOptimizationAdvisor

    def advise(payload, feedback=""):
        freq = payload.get("frequency") or {}
        blast = payload.get("blast_radius") or {}
        return LogOptimizationAdvisor().suggest(
            service=payload.get("service") or "unknown",
            kind=payload.get("kind") or "volume",
            subject=payload.get("subject") or payload.get("service") or "unknown",
            last_window_count=int(freq.get("last_window") or 0),
            runs_observed=int(freq.get("runs_observed") or 0),
            share_pct=float(blast.get("share_pct") or 0.0),
            feedback=feedback,
        )

    def suggestion_text(suggestion):
        # The full grounding surface the verifier checks against the pattern.
        return f"{suggestion.assessment} {suggestion.recommendation}"

    def build_comment(suggestion):
        if suggestion is None:
            return (
                "📉 Optimization agent reviewed this pattern but couldn't justify a "
                "confident change from the frequency data alone — worth a human look."
            )
        win = f"\n\nExpected win: {suggestion.resource_win}." if suggestion.resource_win else ""
        return (
            f"📉 Optimization agent analyzed this log pattern.\n\n"
            f"Assessment: {suggestion.assessment}\n\n"
            f"Recommendation: {suggestion.recommendation}{win}\n\n"
            f"Confidence: {suggestion.confidence}."
        )

    def apply_payload(payload, suggestion):
        payload["recommendation"] = suggestion.recommendation
        payload["suggested_fix"] = suggestion.recommendation
        payload["probable_cause"] = suggestion.assessment
        payload["resource_win"] = suggestion.resource_win
        payload["confidence"] = suggestion.confidence

    def describe_action(suggestion):
        if suggestion is None:
            return "reviewed; no confident recommendation from the frequency data"
        return f"recommended an optimization ({suggestion.confidence} confidence)"

    return fp.process_pending_finding(
        agent,
        input_str,
        source_type=_LOG_OPTIMIZATION_SOURCE,
        column_title=OPTIMIZE_COLUMN_TITLE,
        acting_agent="optimization_agent",
        advise=advise,
        build_comment=build_comment,
        apply_payload=apply_payload,
        describe_action=describe_action,
        suggestion_text=suggestion_text,
    )

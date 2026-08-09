"""Attach each ranked finding's triage state — shared by the list and detail reads.

Both read paths need the same thing: resolve the batch's states through the port in
ONE call, then pair each row with its state (or the honest "not routed" default when
the finding never became a board card). That choreography lives here once rather
than being copy-pasted into two use cases, so the two reads can never drift on what
a finding's state means.

Framework-free (application layer) and fail-safe: if the port is absent or errors,
findings are returned unchanged with ``triage=None``. The triage block is additive
context — it must never take the findings list down.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from components.findings.application.ports.finding_triage_state_port import FindingTriageStatePort
from components.findings.application.queries.finding_triage_state_query import derive_triage_state

logger = logging.getLogger(__name__)


def attach_triage_states(
    rows: Sequence,
    triage_states: FindingTriageStatePort | None,
    *,
    workspace_id,
) -> list:
    """Return *rows* with their ``triage`` state attached."""
    rows = list(rows)
    if triage_states is None or not rows:
        return rows
    try:
        states = triage_states.states_for(
            workspace_id=workspace_id, finding_ids=[str(r.finding.id) for r in rows]
        )
    except Exception:
        logger.exception("finding_triage_state_lookup_failed workspace_id=%s", workspace_id)
        return rows
    # A finding with no card is not an error — it is genuinely not routed, and
    # ``derive_triage_state(card=None)`` says exactly that.
    return [
        replace(row, triage=states.get(str(row.finding.id)) or derive_triage_state(card=None)) for row in rows
    ]

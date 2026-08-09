"""The finding-triage contract — shared by everyone who writes, routes, or reads it.

Three bounded contexts need to agree on "is this finding going to get an automated
fix, and where is it in that journey":

* ``agents`` WRITES the routing target (the board handler stamps ``agent_type`` on
  the card) and ROUTES on it (the finding router dispatches the specialist).
* ``findings`` READS it, to tell the HUD why a finding does or does not have a fix
  yet — the whole point of this contract: a finding must never sit in an
  unexplained gap between "detected" and "fix proposed".
* ``project`` stores the card the state is derived from.

Per the component-decoupling rules (C1), a contract shared across contexts lives in
the shared kernel so no context imports another to understand it. Framework-free —
no Django, no ORM, no infrastructure.
"""

from __future__ import annotations

from enum import Enum


class TriageState(str, Enum):
    """Where a finding is between "detected" and "fix proposed".

    Every value is DERIVED from data that actually exists on the finding's board
    card — none is guessed, and none is a placeholder for "we don't know".
    """

    #: A specialist owns this finding and has not run yet. Carries ``next_triage_at``
    #: so the operator is told WHEN, never left waiting on nothing.
    QUEUED = "queued"
    #: A specialist run is in flight for this finding right now.
    DRAFTING = "drafting"
    #: The specialist produced a grounded fix; the draft-PR affordance is live.
    FIX_READY = "fix_ready"
    #: A fix was produced but could not be grounded (or the source content is
    #: untrusted) — a person decides. It never becomes an automatic pull request.
    NEEDS_HUMAN = "needs_human"
    #: The specialist ran and honestly could not derive a fix from the evidence.
    NO_FIX = "no_fix"
    #: This finding has no automated fix path at all — an operator-reading finding
    #: (cloud posture, planted instructions) or one below the board threshold.
    NOT_ROUTED = "not_routed"


# Finding ``source_type``s whose cards are routed to a specialist. Growing this is
# the ENTIRE routing change needed for a new finding kind (plus the specialist's
# triage tool — "routable without a tool is a silent no-op").
ROUTABLE_SOURCE_TYPES: tuple[str, ...] = (
    "ai.log_watch",
    "ai.log_optimization",
    "ai.cloud_exposure",
    "ai.container_security",
    "ai.code_security",
)

# ``agent_type`` values that are NOT a dispatchable specialist. A card stamped with
# one of these is deliberately operator-reading material (the orchestrator is not a
# board-acting specialist and has no triage tool), so it is never dispatched — and
# the HUD says NOT ROUTED rather than leaving a silent blank.
NON_SPECIALIST_AGENT_TYPES: frozenset[str] = frozenset({"", "ai_teammate", "ai_teammate_agent", "orchestrator"})


def is_routable_to_specialist(source_type: str, agent_type: str) -> bool:
    """True when a card of *source_type* declaring *agent_type* gets automated triage."""
    return (source_type or "") in ROUTABLE_SOURCE_TYPES and (agent_type or "").strip() not in NON_SPECIALIST_AGENT_TYPES


# How long an in-flight ``triage_dispatch`` stamp is believed. Part of the CONTRACT,
# not one side's private constant: the agents pipeline writes the stamp and the
# findings read path interprets it, so a drift between them would show DRAFTING
# forever (or never). The dispatch task's hard time limit is ``AGENT_TIME_LIMIT * 3``
# (450s by default); past this window the run is gone and the finding honestly falls
# back to QUEUED with the next cadence pass named.
DISPATCH_STAMP_TTL_SECONDS = 600

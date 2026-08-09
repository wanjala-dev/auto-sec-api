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
    #: The specialist produced a grounded, verified fix; the draft-PR affordance
    #: is live.
    FIX_READY = "fix_ready"
    #: A fix was produced but could not be VERIFIED against the finding's own
    #: evidence (or the source content is untrusted). The artifact still ships —
    #: the draft PR opens, loudly labeled UNVERIFIED with the named evidence gap —
    #: because a draft PR cannot merge itself: the PR *is* the human review
    #: surface. The label downgrades; it never withholds. (Replaces the old
    #: dead-end ``needs_human`` state, which held the fix and left the operator
    #: a chip with no artifact.)
    FIX_UNVERIFIED = "fix_unverified"
    #: The specialist ran and honestly could not derive a fix from the evidence.
    #: Carries WHY (what was missing) and stays re-attemptable — the on-demand
    #: draft-fix action re-runs the specialist rather than dead-ending.
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

# ── Remediation target — WHERE a finding's fix lands ─────────────────────────
#
# The artifact must MATCH the target. A finding whose subject lives in a
# connected repository (a traceback into the customer's code, a SAST hit at a
# file:line) is remediated by a DRAFT PR. A finding whose subject is an
# artifact we cannot open a PR against — a container image with no linked repo
# (public nginx/node images, or any image URL a user points a scan at), a cloud
# resource, a runtime service config — is remediated by a FIX SNIPPET /
# guidance: offering a draft-PR affordance there is a doomed click, and
# attempting one produces "finding not found" noise on the board.

#: Sources whose findings the draft-PR engine can act on. ONE definition —
#: the engine's finding-facts gate and the read paths that decide whether to
#: offer the PR affordance both derive from this, so they can never disagree
#: (the pre-fix bug: the triage state offered ``can_draft_fix`` for container
#: findings the engine then refused as ``finding_not_found``).
PR_REMEDIABLE_SOURCE_TYPES: tuple[str, ...] = ("ai.log_watch", "ai.code_security")

#: Remediation-target values.
TARGET_REPO = "repo"  # connected+allowlisted repository → draft-PR path
TARGET_IMAGE = "image"  # container image with no linked repo → fix snippet
TARGET_CLOUD = "cloud"  # cloud resource/config → operator guidance
TARGET_SERVICE = "service"  # runtime service/log config → operator guidance
TARGET_NONE = "none"  # operator-reading material — no automated artifact


def remediation_target(source_type: str, payload: dict | None = None) -> str:
    """WHERE this finding's fix lands — ``repo`` | ``image`` | ``cloud`` |
    ``service`` | ``none``.

    Only ``repo`` carries the draft-PR affordance. A container finding whose
    payload names a connected repo (an image traceable to a repo build — the
    future seam) flips to ``repo``; today's Trivy payloads never carry one, so
    public/unlinked images honestly resolve to ``image``.
    """
    st = (source_type or "").strip()
    if st in PR_REMEDIABLE_SOURCE_TYPES:
        return TARGET_REPO
    if st == "ai.container_security":
        linked_repo = str((payload or {}).get("repo") or "").strip()
        return TARGET_REPO if linked_repo else TARGET_IMAGE
    if st == "ai.cloud_exposure":
        return TARGET_CLOUD
    if st == "ai.log_optimization":
        return TARGET_SERVICE
    return TARGET_NONE


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

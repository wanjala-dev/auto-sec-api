"""Derive a finding's triage state — the answer to "why is there no fix yet?".

A scan files a finding into the SSOT instantly, but the fix arrives later, from a
specialist run. Between those two moments the HUD used to show only the rule's
generic guidance ("Review <file>:<line> and apply the rule guidance") with no fix,
no draft-PR affordance, and no explanation — which reads as "the product does
nothing". This module turns the facts already recorded on the finding's board card
into an honest state the UI can always render.

Every value is DERIVED from real data — the card's ``metadata.triage`` stamp, its
``metadata.payload``, and the in-flight ``metadata.triage_dispatch`` stamp a
starting dispatch writes. Nothing here guesses; when there is genuinely no automated
path, the state says so (``NOT_ROUTED``) rather than leaving a blank.

Framework-free by design (application layer): the Django/ORM/cadence side lives in
the adapter that feeds this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from components.project.application.ports.record_finding_draft_pr_port import get_draft_pr
from components.shared_kernel.domain.triage import TriageState, is_routable_to_specialist


@dataclass(frozen=True)
class FindingTriageStateView:
    """The read model the HUD renders for one finding."""

    state: str
    #: The specialist that owns (or owned) this finding, when it is routed.
    specialist: str = ""
    #: When the next cadence pass runs — populated for QUEUED so the operator is
    #: told WHEN, never left waiting on an unbounded "soon".
    next_triage_at: datetime | None = None
    #: Human-readable "why this state", already carried by the pipeline today.
    reason: str = ""
    #: The board card this state came from — the id the draft-fix / draft-PR
    #: endpoints take (they are keyed by task, not by SSOT finding id).
    task_id: str = ""
    triaged_at: str = ""
    suggested_fix: str = ""
    confidence: str = ""
    draft_pr: dict | None = None
    #: A fix exists but a guardrail refused the pull request (scope, throttle,
    #: confidence). Surfaced so a blocked PR is visible, never silent.
    blocked_reason: str = ""
    #: True when the operator's on-demand "draft a fix PR" action is available.
    can_draft_fix: bool = False
    factors: tuple[str, ...] = field(default_factory=tuple)


_NOT_ROUTED_REASON = (
    "This finding has no automated fix path — it is operator-reading material, "
    "not something an agent proposes a code change for."
)
_NO_CARD_REASON = "This finding is below the board threshold, so no specialist was assigned. It stays here for review."


def derive_triage_state(
    *,
    card: dict | None,
    next_triage_at: datetime | None = None,
    dispatch_stamp_is_fresh: bool = False,
) -> FindingTriageStateView:
    """Map one finding's board card onto its triage state.

    ``card`` is a plain mapping (``source_type``, ``task_id``, ``metadata``) so this
    stays ORM-free and directly unit-testable. ``None`` means the finding never
    became a card.

    Order matters: the finished states are checked BEFORE the in-flight one, so a
    stale ``triage_dispatch`` stamp can never mask a fix that already landed.
    """
    if not card:
        return FindingTriageStateView(state=TriageState.NOT_ROUTED.value, reason=_NO_CARD_REASON)

    metadata = card.get("metadata") or {}
    source_type = str(card.get("source_type") or "")
    specialist = str(metadata.get("agent_type") or "").strip()
    task_id = str(card.get("task_id") or "")

    if not is_routable_to_specialist(source_type, specialist):
        return FindingTriageStateView(
            state=TriageState.NOT_ROUTED.value, specialist=specialist, task_id=task_id, reason=_NOT_ROUTED_REASON
        )

    triage = metadata.get("triage") or {}
    payload = metadata.get("payload") or {}
    blocked = metadata.get("draft_pr_blocked") or {}
    # Read through the recording contract's ONE accessor (#264) so this reader can
    # never drift from the writer's shape — the exact failure that fix addressed.
    draft_pr = get_draft_pr(metadata) or None
    base = {
        "specialist": specialist,
        "task_id": task_id,
        "triaged_at": str(triage.get("triaged_at") or ""),
        "draft_pr": draft_pr if draft_pr and draft_pr.get("url") else None,
    }

    if triage.get("status") == "triaged":
        needs_human = bool(triage.get("needs_human") or payload.get("needs_human"))
        suggested_fix = str(payload.get("suggested_fix") or "")
        confidence = str(payload.get("confidence") or "")
        if needs_human:
            return FindingTriageStateView(
                state=TriageState.NEEDS_HUMAN.value,
                reason=str(payload.get("needs_human_reason") or "")
                or (
                    "The suggested fix could not be grounded in this finding's own evidence, "
                    "so it is held for a person. It never becomes an automatic pull request."
                ),
                suggested_fix=suggested_fix,
                confidence=confidence,
                **base,
            )
        if suggested_fix or triage.get("suggested"):
            return FindingTriageStateView(
                state=TriageState.FIX_READY.value,
                suggested_fix=suggested_fix,
                confidence=confidence,
                blocked_reason=str(blocked.get("reason") or ""),
                reason=str(blocked.get("message") or ""),
                can_draft_fix=base["draft_pr"] is None,
                **base,
            )
        return FindingTriageStateView(
            state=TriageState.NO_FIX.value,
            reason=(
                "The specialist reviewed this finding and could not derive a confident fix "
                "from the rule and file alone — it needs a human eye."
            ),
            **base,
        )

    if dispatch_stamp_is_fresh:
        return FindingTriageStateView(
            state=TriageState.DRAFTING.value,
            reason="A specialist is analysing this finding and drafting a fix right now.",
            **base,
        )

    return FindingTriageStateView(
        state=TriageState.QUEUED.value,
        next_triage_at=next_triage_at,
        reason=(
            f"Queued for {specialist.replace('_', ' ')} — it will propose a fix on the next pass."
            if specialist
            else "Queued for triage."
        ),
        can_draft_fix=True,
        **base,
    )

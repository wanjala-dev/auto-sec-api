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
from components.shared_kernel.domain.triage import (
    TARGET_REPO,
    TriageState,
    is_routable_to_specialist,
    remediation_target,
)


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
    #: "verified" | "unverified" | "" — the fix's confidence LABEL. ``unverified``
    #: means the suggestion could not be grounded in the finding's own evidence
    #: (or the source content is untrusted); the artifact still exists/ships.
    verification: str = ""
    #: The named evidence gap when ``verification == "unverified"``.
    verification_gap: str = ""
    draft_pr: dict | None = None
    #: WHERE this finding's fix lands: ``repo`` (draft-PR path) | ``image`` (fix
    #: snippet — no linked repo to PR against) | ``cloud`` | ``service`` |
    #: ``none``. The artifact must MATCH the target: only ``repo`` findings ever
    #: carry the draft-PR affordance.
    remediation_target: str = ""
    #: The image-target artifact: copy-pasteable Dockerfile/package guidance,
    #: rendered by the HUD through the sanitized code block. Empty for repo
    #: findings (their artifact is the draft PR).
    fix_snippet: str = ""
    fix_snippet_language: str = ""
    #: A fix exists but a guardrail refused the pull request (scope, throttle,
    #: confidence). Surfaced so a blocked PR is visible, never silent.
    blocked_reason: str = ""
    #: True when the operator's on-demand "draft a fix PR" action is available.
    #: Always False off the ``repo`` target — offering the button for an
    #: unlinked image was a doomed click (the engine refused it as
    #: ``finding_not_found`` after burning a specialist run).
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
    # The artifact must MATCH the target: repo findings get the PR affordance,
    # image findings get the fix snippet, cloud/service findings get guidance.
    target = remediation_target(source_type, payload)
    pr_target = target == TARGET_REPO
    base = {
        "specialist": specialist,
        "task_id": task_id,
        "triaged_at": str(triage.get("triaged_at") or ""),
        "draft_pr": draft_pr if draft_pr and draft_pr.get("url") else None,
        "remediation_target": target,
        "fix_snippet": str(payload.get("fix_snippet") or ""),
        "fix_snippet_language": str(payload.get("fix_snippet_language") or ""),
    }

    if triage.get("status") == "triaged":
        suggested_fix = str(payload.get("suggested_fix") or "")
        confidence = str(payload.get("confidence") or "")
        unverified = (
            str(payload.get("verification") or "").strip().lower() == "unverified"
            # Legacy rows stamped before verification labels existed.
            or bool(triage.get("needs_human") or payload.get("needs_human"))
        )
        gap = str(
            payload.get("verification_gap") or triage.get("verification_gap") or payload.get("needs_human_reason") or ""
        )
        if suggested_fix or triage.get("suggested"):
            if unverified:
                # A fix EXISTS — it just failed verification. The label downgrades
                # (a repo finding's draft PR opens/opened marked [UNVERIFIED]; an
                # image finding's snippet carries the same warning); the artifact
                # is never withheld.
                return FindingTriageStateView(
                    state=TriageState.FIX_UNVERIFIED.value,
                    reason=(
                        "Review carefully — this fix could not be grounded against the "
                        f"finding's own evidence ({gap or 'no named anchor'}). "
                        + (
                            "Its draft PR is clearly labeled UNVERIFIED; the PR review is the human gate."
                            if pr_target
                            else "Treat the suggested fix/snippet as a starting point, not a vetted fix."
                        )
                    ),
                    suggested_fix=suggested_fix,
                    confidence=confidence,
                    verification="unverified",
                    verification_gap=gap,
                    blocked_reason=str(blocked.get("reason") or ""),
                    can_draft_fix=pr_target and base["draft_pr"] is None,
                    **base,
                )
            return FindingTriageStateView(
                state=TriageState.FIX_READY.value,
                suggested_fix=suggested_fix,
                confidence=confidence,
                verification=str(payload.get("verification") or ""),
                blocked_reason=str(blocked.get("reason") or ""),
                reason=str(blocked.get("message") or ""),
                can_draft_fix=pr_target and base["draft_pr"] is None,
                **base,
            )
        no_fix_why = str(triage.get("no_fix_reason") or "").strip()
        return FindingTriageStateView(
            state=TriageState.NO_FIX.value,
            reason=(
                (
                    f"The specialist ran and could not derive a fix: {no_fix_why}."
                    if no_fix_why
                    else (
                        "The specialist reviewed this finding and could not derive a confident "
                        "fix from the rule and file alone."
                    )
                )
                + (
                    " Retry available — DRAFT FIX PR re-runs the specialist with fresh context."
                    if pr_target
                    else " The next scheduled pass will retry with fresh context."
                )
            ),
            # The retry affordance: a no-fix outcome is re-attemptable, never a
            # dead end. (Repo targets only — the on-demand action is the PR
            # pipeline's trigger; non-repo findings retry on the cadence.)
            can_draft_fix=pr_target,
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
        can_draft_fix=pr_target,
        **base,
    )

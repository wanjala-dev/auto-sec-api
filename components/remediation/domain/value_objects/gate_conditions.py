"""The three gate conditions (ADR 0012 D1) as immutable domain facts.

``GateConditions`` is the single struct the entry-gate evaluates. It is a pure
domain value object — no framework, no I/O. The *facts* it carries are gathered
by the application layer through read-ports (sign-off state, finding state); the
*decision* is made here so the rule "all three must hold" lives in one place and
is unit-testable without a database.

The rule is deliberately conjunctive and total: an entry may be admitted **only**
when every condition is satisfied. There is no partial credit, no override.
"""

from __future__ import annotations

from dataclasses import dataclass

# Stable reason codes for each unmet condition — surfaced in the refusal error
# and (later) the audit trail. Keep these strings stable; tests assert on them.
REASON_NOT_APPROVED = "sign_off_not_approved"
REASON_NOT_APPLIED = "draft_pr_not_applied"
REASON_NOT_RESOLVED = "finding_not_resolved"


@dataclass(frozen=True)
class GateConditions:
    """The three facts the D1 entry-gate requires, all of which must be True.

    - ``sign_off_approved``: a sign-off record for this remediation is APPROVED.
    - ``draft_pr_applied``: the draft PR that carried the fix was actually
      applied (merged). Because merge-detection is not yet built (see
      ``FindingRemediationFactsPort``), this is set from an explicit operator
      confirmation, never inferred from a draft PR merely being *open*.
    - ``finding_resolved``: the finding this fix targets is observed resolved.
    """

    sign_off_approved: bool
    draft_pr_applied: bool
    finding_resolved: bool

    @property
    def satisfied(self) -> bool:
        """True only when all three conditions hold."""
        return self.sign_off_approved and self.draft_pr_applied and self.finding_resolved

    def unmet_reasons(self) -> tuple[str, ...]:
        """The reason codes for whichever conditions are not satisfied (in a
        stable order). Empty when the gate is fully satisfied."""
        reasons: list[str] = []
        if not self.sign_off_approved:
            reasons.append(REASON_NOT_APPROVED)
        if not self.draft_pr_applied:
            reasons.append(REASON_NOT_APPLIED)
        if not self.finding_resolved:
            reasons.append(REASON_NOT_RESOLVED)
        return tuple(reasons)

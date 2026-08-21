"""How strong a claim a suite's evidence can support (ADR 0033 D9).

The field says >=500 cases before aggregate metrics are trustworthy. The
Anthropic course material says 10+ per axis. Both are right about different
claims, and no young workspace has either. Splitting the difference quietly
would produce a confident number from six cases, which is the defect this
codebase keeps shipping — so the tier is stated on the surface instead.

The floor is the same 10 as ``code_security.domain.fix_confidence``'s
``AUTOFIX_MIN_TRIALS``. It is DECLARED here rather than imported: a domain that
reaches into another context's domain is a boundary violation, and the
architecture suite rightly refuses it (it caught exactly that in the first
draft of this file).

Duplicating a constant is normally the wrong trade. It is acceptable here only
because the agreement is asserted — ``test_claim_tier.py`` fails if the two
values ever diverge — so drift is caught by a test rather than discovered when
two surfaces disagree about when evidence becomes a judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Where a rate stops being noise. Must equal
#: ``code_security.domain.fix_confidence.AUTOFIX_MIN_TRIALS`` — enforced by test.
MIN_OBSERVATIONS = 10

#: Where per-axis measurement becomes stable enough to trend and to calibrate a
#: judge against human labels (the literature's 50-200 calibration-set range).
MEASURED_THRESHOLD = 50

#: Where aggregate comparison across models and time becomes defensible.
AGGREGATE_THRESHOLD = 500


class ClaimTier(Enum):
    """What a panel is ALLOWED to say about an axis, given its sample size."""

    NOT_MEASURED = "not_measured"
    DIRECTIONAL = "directional"
    MEASURED = "measured"
    AGGREGATE_GRADE = "aggregate_grade"

    @property
    def label(self) -> str:
        return {
            ClaimTier.NOT_MEASURED: "NOT MEASURED",
            ClaimTier.DIRECTIONAL: "DIRECTIONAL",
            ClaimTier.MEASURED: "MEASURED",
            ClaimTier.AGGREGATE_GRADE: "AGGREGATE-GRADE",
        }[self]

    @property
    def may_state_rate(self) -> bool:
        """Below the floor we report a COUNT, never a percentage.

        A rate implies a denominator big enough to mean something. Rendering
        "0 of 3 — 0%" invites reading a catastrophe into three observations.
        """
        return self is not ClaimTier.NOT_MEASURED

    @property
    def may_conclude(self) -> bool:
        """Whether this tier supports a verdict rather than an indication."""
        return self in (ClaimTier.MEASURED, ClaimTier.AGGREGATE_GRADE)

    @property
    def may_compare(self) -> bool:
        """Whether comparing two runs (models, time) is defensible."""
        return self is ClaimTier.AGGREGATE_GRADE


def tier_for(observations: int) -> ClaimTier:
    """The strongest claim ``observations`` can support.

    Deliberately total: a negative count cannot arise from a real query, but
    treating it as NOT_MEASURED rather than raising means a corrupt counter
    degrades the claim instead of taking down the panel.
    """
    if observations < MIN_OBSERVATIONS:
        return ClaimTier.NOT_MEASURED
    if observations < MEASURED_THRESHOLD:
        return ClaimTier.DIRECTIONAL
    if observations < AGGREGATE_THRESHOLD:
        return ClaimTier.MEASURED
    return ClaimTier.AGGREGATE_GRADE


#: The strongest claim a SELF-AUTHORED suite may support (ADR 0033 D14).
#:
#: Every threshold above answers "how many observations is enough". This one
#: answers a different question that no count can settle: where the cases came
#: from. A mined suite is a SAMPLE of what the agent actually faced. An uploaded
#: suite is a SELECTION — someone chose which questions to ask, and nothing
#: stops them choosing ten the agent already handles.
#:
#: Without this cap the two are indistinguishable on screen: ten uploaded cases
#: clear MIN_OBSERVATIONS exactly as ten mined ones do, and 500 clear
#: AGGREGATE_THRESHOLD. The resulting "AGGREGATE-GRADE, 100%" would be true and
#: useless, and it would arrive through the front door of a feature we built.
#:
#: DIRECTIONAL is the honest ceiling. A self-authored suite can support "the
#: agent handled the cases you chose"; it cannot support "the agent is good at
#: this", which is what MEASURED and above assert.
SELF_AUTHORED_CEILING = ClaimTier.DIRECTIONAL


def cap_for_provenance(tier: ClaimTier, *, self_authored: bool) -> ClaimTier:
    """Lower a tier to what its PROVENANCE can support.

    Only ever lowers. A self-authored suite below the ceiling keeps its own
    (lower) tier rather than being raised to it — twelve uploaded cases are
    still twelve cases, and three are still NOT MEASURED.
    """
    if not self_authored:
        return tier
    if tier in (ClaimTier.MEASURED, ClaimTier.AGGREGATE_GRADE):
        return SELF_AUTHORED_CEILING
    return tier

@dataclass(frozen=True)
class AxisEvidence:
    """One axis's result, carrying its own denominator and claim tier.

    A rate without its denominator is a guess with a percent sign, so the two
    travel together and the tier is derived rather than assigned.
    """

    axis: str
    passed: int
    measured: int
    #: Set when the cases were authored by the customer rather than mined from
    #: their history. Carried on the evidence itself so the ceiling travels with
    #: the number instead of having to be re-applied by every reader.
    self_authored: bool = False

    def __post_init__(self) -> None:
        if self.passed < 0 or self.measured < 0:
            raise ValueError("counts cannot be negative")
        if self.passed > self.measured:
            raise ValueError(f"passed ({self.passed}) cannot exceed measured ({self.measured})")

    @property
    def tier(self) -> ClaimTier:
        return cap_for_provenance(tier_for(self.measured), self_authored=self.self_authored)

    @property
    def pass_rate(self) -> float | None:
        """``None`` below the floor — not zero, and not omitted silently.

        Callers must render the absence, because a missing rate and a rate of
        0.0 mean opposite things and this product has shipped that confusion
        before.
        """
        if not self.tier.may_state_rate or self.measured == 0:
            return None
        return self.passed / self.measured

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "passed": self.passed,
            "measured": self.measured,
            "pass_rate": self.pass_rate,
            "tier": self.tier.value,
            "tier_label": self.tier.label,
            "may_conclude": self.tier.may_conclude,
            "self_authored": self.self_authored,
        }


__all__ = [
    "AGGREGATE_THRESHOLD",
    "SELF_AUTHORED_CEILING",
    "MEASURED_THRESHOLD",
    "MIN_OBSERVATIONS",
    "AxisEvidence",
    "ClaimTier",
    "cap_for_provenance",
    "tier_for",
]

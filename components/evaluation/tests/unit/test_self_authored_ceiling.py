"""The claim ceiling on suites a workspace wrote itself.

Every other threshold in `claim_tier` answers "how many observations is enough".
This one answers a question no count can settle: where the cases came from.

A mined suite is a SAMPLE of what the agent actually faced. An authored suite is
a SELECTION — someone chose which questions to ask, and nothing stops them
choosing ten the agent already handles. Without the cap the two are
indistinguishable on screen, because 500 authored cases clear
AGGREGATE_THRESHOLD exactly as 500 mined ones do. The resulting
"AGGREGATE-GRADE, 100%" would be true and useless.
"""

from __future__ import annotations

import pytest

from components.evaluation.domain.value_objects.claim_tier import (
    AGGREGATE_THRESHOLD,
    MEASURED_THRESHOLD,
    MIN_OBSERVATIONS,
    SELF_AUTHORED_CEILING,
    AxisEvidence,
    ClaimTier,
    cap_for_provenance,
    tier_for,
)

pytestmark = [pytest.mark.unit]


class TestTheCeiling:
    def test_a_self_authored_suite_never_reaches_aggregate_grade(self):
        """The headline. 500 cases you wrote yourself do not make a general
        claim about the agent, however many there are."""
        assert tier_for(AGGREGATE_THRESHOLD) is ClaimTier.AGGREGATE_GRADE

        assert cap_for_provenance(tier_for(AGGREGATE_THRESHOLD), self_authored=True) is SELF_AUTHORED_CEILING

    def test_a_self_authored_suite_never_reaches_measured(self):
        assert cap_for_provenance(tier_for(MEASURED_THRESHOLD), self_authored=True) is ClaimTier.DIRECTIONAL

    def test_a_mined_suite_is_untouched(self):
        for count in (MIN_OBSERVATIONS, MEASURED_THRESHOLD, AGGREGATE_THRESHOLD):
            assert cap_for_provenance(tier_for(count), self_authored=False) is tier_for(count)

    def test_the_cap_only_ever_lowers(self):
        """Twelve authored cases are still twelve cases. Raising a low tier UP
        to the ceiling would invent evidence rather than limit a claim."""
        assert cap_for_provenance(ClaimTier.NOT_MEASURED, self_authored=True) is ClaimTier.NOT_MEASURED
        assert cap_for_provenance(ClaimTier.DIRECTIONAL, self_authored=True) is ClaimTier.DIRECTIONAL

    def test_three_authored_cases_are_still_not_measured(self):
        assert cap_for_provenance(tier_for(3), self_authored=True) is ClaimTier.NOT_MEASURED


class TestEvidenceCarriesItsOwnProvenance:
    def test_an_authored_axis_reports_the_capped_tier(self):
        """The ceiling travels with the evidence rather than having to be
        re-applied by every reader — a reader that forgot would print the
        uncapped tier and nothing would catch it."""
        evidence = AxisEvidence(axis="grounded", passed=600, measured=600, self_authored=True)

        assert evidence.tier is ClaimTier.DIRECTIONAL
        assert evidence.as_dict()["tier_label"] == "DIRECTIONAL"
        assert evidence.as_dict()["self_authored"] is True

    def test_a_mined_axis_with_the_same_numbers_reports_aggregate_grade(self):
        evidence = AxisEvidence(axis="grounded", passed=600, measured=600)

        assert evidence.tier is ClaimTier.AGGREGATE_GRADE

    def test_the_cap_does_not_suppress_the_rate_itself(self):
        """DIRECTIONAL still states a rate. The cap limits what may be
        CONCLUDED from it, not whether the number is shown — hiding it would
        make an authored suite useless rather than honest."""
        evidence = AxisEvidence(axis="grounded", passed=45, measured=60, self_authored=True)

        assert evidence.pass_rate == pytest.approx(0.75)
        assert evidence.tier.may_state_rate is True
        assert evidence.tier.may_conclude is False

    def test_an_authored_axis_may_never_be_compared_across_runs(self):
        evidence = AxisEvidence(axis="grounded", passed=600, measured=600, self_authored=True)

        assert evidence.tier.may_compare is False

    def test_below_the_floor_an_authored_rate_is_still_withheld(self):
        evidence = AxisEvidence(axis="grounded", passed=2, measured=3, self_authored=True)

        assert evidence.pass_rate is None

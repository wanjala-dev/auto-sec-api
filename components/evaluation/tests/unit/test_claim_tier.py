"""What a suite is allowed to claim, given how much it measured (ADR 0033 D9).

These are boundary tests because the boundaries are the whole point. The
failure this guards against is not a wrong percentage — it is a CONFIDENT
percentage computed from six observations, which is how a panel ends up
asserting something the evidence cannot support.
"""

from __future__ import annotations

import pytest

from components.code_security.domain.fix_confidence import AUTOFIX_MIN_TRIALS
from components.evaluation.domain.value_objects.claim_tier import (
    AGGREGATE_THRESHOLD,
    MEASURED_THRESHOLD,
    MIN_OBSERVATIONS,
    AxisEvidence,
    ClaimTier,
    tier_for,
)

pytestmark = [pytest.mark.unit]


class TestTierBoundaries:
    @pytest.mark.parametrize(
        "observations,expected",
        [
            (0, ClaimTier.NOT_MEASURED),
            (1, ClaimTier.NOT_MEASURED),
            (MIN_OBSERVATIONS - 1, ClaimTier.NOT_MEASURED),
            (MIN_OBSERVATIONS, ClaimTier.DIRECTIONAL),
            (MEASURED_THRESHOLD - 1, ClaimTier.DIRECTIONAL),
            (MEASURED_THRESHOLD, ClaimTier.MEASURED),
            (AGGREGATE_THRESHOLD - 1, ClaimTier.MEASURED),
            (AGGREGATE_THRESHOLD, ClaimTier.AGGREGATE_GRADE),
            (10_000, ClaimTier.AGGREGATE_GRADE),
        ],
    )
    def test_each_boundary(self, observations, expected):
        assert tier_for(observations) is expected

    def test_the_floor_is_the_products_existing_one(self):
        """Not a second threshold with the same job and a different value.

        If this ever fails, two surfaces have started disagreeing about when
        evidence becomes a judgement — which is worse than either value.
        """
        assert MIN_OBSERVATIONS == AUTOFIX_MIN_TRIALS

    def test_a_corrupt_counter_degrades_the_claim_rather_than_crashing(self):
        assert tier_for(-1) is ClaimTier.NOT_MEASURED


class TestWhatEachTierMaySay:
    def test_below_the_floor_no_rate_may_be_stated(self):
        assert ClaimTier.NOT_MEASURED.may_state_rate is False

    def test_directional_may_state_a_rate_but_not_conclude(self):
        assert ClaimTier.DIRECTIONAL.may_state_rate is True
        assert ClaimTier.DIRECTIONAL.may_conclude is False

    def test_only_aggregate_grade_may_be_compared(self):
        assert ClaimTier.MEASURED.may_compare is False
        assert ClaimTier.AGGREGATE_GRADE.may_compare is True


class TestAxisEvidence:
    def test_below_the_floor_the_rate_is_none_not_zero(self):
        """None and 0.0 mean opposite things, and this product has shipped
        that confusion before — an empty report reading as a clean one."""
        evidence = AxisEvidence(axis="grounded", passed=0, measured=3)

        assert evidence.pass_rate is None
        assert evidence.tier is ClaimTier.NOT_MEASURED

    def test_a_perfect_small_sample_still_does_not_conclude(self):
        """3 of 3 is not evidence of a flawless agent. This is the direction
        of error nobody notices, because the number looks good."""
        evidence = AxisEvidence(axis="grounded", passed=3, measured=3)

        assert evidence.pass_rate is None
        assert evidence.tier.may_conclude is False

    def test_the_rate_carries_its_denominator(self):
        evidence = AxisEvidence(axis="fix_applies", passed=41, measured=50)

        assert evidence.pass_rate == pytest.approx(0.82)
        assert evidence.measured == 50
        assert evidence.as_dict()["measured"] == 50

    def test_passed_cannot_exceed_measured(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            AxisEvidence(axis="grounded", passed=5, measured=3)

    def test_counts_cannot_be_negative(self):
        with pytest.raises(ValueError, match="negative"):
            AxisEvidence(axis="grounded", passed=-1, measured=3)

    def test_zero_measured_yields_no_rate(self):
        evidence = AxisEvidence(axis="grounded", passed=0, measured=0)

        assert evidence.pass_rate is None
        assert evidence.tier is ClaimTier.NOT_MEASURED

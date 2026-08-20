"""The one statistic must stay honest on small samples, and stay ONE.

Two things are defended here:

1. **The numbers.** The Wilson bounds are pinned to the calibration points
   ``fix_confidence``'s own docstring quotes (2/2 → 0.43, 20/20 → 0.88), so
   generalising the module out of ``code_security`` cannot have changed what
   its existing caller computes.
2. **The three states.** ``no_data`` is a distinct verdict, never a good one
   (ADR 0032 D4). A panel reading green because nothing ran is the #415
   defect wearing a different hat, and it is asserted here rather than
   reviewed.
"""

from __future__ import annotations

import pytest

from components.shared_kernel.domain.measured_rate import (
    STATE_MEASURED,
    STATE_NO_DATA,
    STATE_TOO_FEW,
    measure_rate,
    rule_of_three_upper_bound,
    wilson_lower_bound,
    wilson_upper_bound,
)

pytestmark = pytest.mark.unit


class TestWilsonBounds:
    def test_perfect_small_sample_is_not_certainty(self):
        """2/2 is barely distinguishable from a coin — 0.43, not 1.0."""
        assert wilson_lower_bound(2, 2) == pytest.approx(0.43, abs=0.01)

    def test_perfect_larger_sample_earns_more(self):
        assert wilson_lower_bound(20, 20) == pytest.approx(0.88, abs=0.01)

    def test_no_trials_scores_zero_not_one(self):
        """Absence of evidence is never read as evidence of adequacy."""
        assert wilson_lower_bound(0, 0) == 0.0

    def test_bounds_stay_inside_the_unit_interval(self):
        for passes, trials in ((0, 1), (1, 1), (7, 13), (0, 100), (100, 100)):
            assert 0.0 <= wilson_lower_bound(passes, trials) <= 1.0
            assert 0.0 <= wilson_upper_bound(passes, trials) <= 1.0
            assert wilson_lower_bound(passes, trials) <= wilson_upper_bound(passes, trials)

    def test_passes_are_clamped_to_trials(self):
        assert wilson_lower_bound(9, 3) == wilson_lower_bound(3, 3)
        assert wilson_lower_bound(-4, 3) == wilson_lower_bound(0, 3)

    def test_zero_failures_does_not_mean_zero_failure_rate(self):
        """A clean streak is not proof. 0/12 failures ≈ up to a 1-in-5 rate."""
        assert wilson_upper_bound(0, 12) > 0.15
        assert rule_of_three_upper_bound(12) == pytest.approx(0.25)

    def test_rule_of_three_with_no_trials_claims_nothing(self):
        assert rule_of_three_upper_bound(0) == 1.0


class TestMeasureRateStates:
    def test_zero_trials_is_no_data_not_a_clean_result(self):
        rate = measure_rate(0, 0, min_trials=10, noun="runs", event="failed")
        assert rate.state == STATE_NO_DATA
        assert rate.point is None
        assert rate.is_measured is False
        assert "Not measured" in rate.summary

    def test_small_sample_is_too_few_and_says_why(self):
        rate = measure_rate(3, 4, min_trials=10, noun="runs", event="passed")
        assert rate.state == STATE_TOO_FEW
        # The "3 of 4 = 75%" failure mode: the fraction is shown, the bare
        # 75% never is, and the reason is spelled out.
        assert "3/4" in rate.summary
        assert "too few" in rate.summary
        assert rate.lower_bound < 0.5

    def test_enough_trials_is_measured_and_carries_n(self):
        rate = measure_rate(18, 20, min_trials=10, noun="runs", event="passed")
        assert rate.state == STATE_MEASURED
        assert rate.trials == 20
        assert rate.is_measured is True

    def test_wire_shape_always_carries_state_and_n(self):
        for observed, trials in ((0, 0), (1, 2), (50, 60)):
            payload = measure_rate(observed, trials, min_trials=10).as_dict()
            assert set(payload) == {
                "state",
                "observed",
                "trials",
                "point",
                "lower_bound",
                "upper_bound",
                "min_trials",
                "summary",
            }
            assert payload["trials"] == trials

    def test_observed_above_trials_is_clamped_not_crashed(self):
        rate = measure_rate(99, 5, min_trials=10)
        assert rate.observed == 5
        assert rate.point == 1.0

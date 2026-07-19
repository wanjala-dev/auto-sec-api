"""Unit tests for the donor-tip money math (pure domain, no DB)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from components.payments.domain.donor_tip import DonorTipBreakdown


RATE = Decimal("0.029")
FIXED = Decimal("0.30")


class TestNoTipNoFeeCoverage:
    def test_total_equals_donation_when_no_tip_and_no_coverage(self):
        b = DonorTipBreakdown.compute(
            donation=Decimal("100.00"), tip=Decimal("0"), currency="USD",
            cover_fees=False, processing_fee_rate=RATE, processing_fee_fixed=FIXED,
        )
        assert b.total == Decimal("100.00")
        assert b.tip == Decimal("0.00")
        assert b.application_fee == Decimal("0.00")
        assert b.fee_coverage == Decimal("0.00")
        assert b.has_tip is False
        # Org absorbs the processor fee: 100 - (0.029*100 + 0.30) = 96.80
        assert b.org_net == Decimal("96.80")


class TestTipWithoutFeeCoverage:
    def test_tip_is_application_fee_and_adds_to_total(self):
        b = DonorTipBreakdown.compute(
            donation=Decimal("100.00"), tip=Decimal("10.00"), currency="usd",
            cover_fees=False, processing_fee_rate=RATE, processing_fee_fixed=FIXED,
        )
        assert b.total == Decimal("110.00")          # donor pays donation + tip
        assert b.application_fee == Decimal("10.00")  # platform take == tip
        assert b.fee_coverage == Decimal("0.00")
        # Org net = 110 - (0.029*110 + 0.30) - 10 = 110 - 3.49 - 10 = 96.51
        assert b.org_net == Decimal("96.51")


class TestFeeCoverageGrossUp:
    def test_org_nets_full_donation_when_fees_covered(self):
        b = DonorTipBreakdown.compute(
            donation=Decimal("100.00"), tip=Decimal("10.00"), currency="USD",
            cover_fees=True, processing_fee_rate=RATE, processing_fee_fixed=FIXED,
        )
        # T = (100 + 10 + 0.30) / (1 - 0.029) = 110.30 / 0.971 = 113.59...
        # rounded up to cents.
        assert b.total >= Decimal("113.59")
        assert b.application_fee == Decimal("10.00")
        assert b.fee_coverage == b.total - b.donation - b.tip
        # The whole point: org is made whole (never short the donation).
        assert b.org_net >= Decimal("100.00")

    def test_org_nets_full_donation_with_no_tip(self):
        b = DonorTipBreakdown.compute(
            donation=Decimal("50.00"), tip=Decimal("0"), currency="USD",
            cover_fees=True, processing_fee_rate=RATE, processing_fee_fixed=FIXED,
        )
        assert b.tip == Decimal("0.00")
        assert b.application_fee == Decimal("0.00")
        assert b.org_net >= Decimal("50.00")
        assert b.fee_coverage > 0


class TestZeroFeeConfig:
    def test_no_processor_fee_means_total_is_donation_plus_tip(self):
        b = DonorTipBreakdown.compute(
            donation=Decimal("100.00"), tip=Decimal("12.00"), currency="USD",
            cover_fees=True, processing_fee_rate=Decimal("0"), processing_fee_fixed=Decimal("0"),
        )
        assert b.total == Decimal("112.00")
        assert b.fee_coverage == Decimal("0.00")
        assert b.org_net == Decimal("100.00")


class TestValidation:
    def test_zero_donation_rejected(self):
        with pytest.raises(ValueError):
            DonorTipBreakdown.compute(
                donation=Decimal("0"), tip=Decimal("0"), currency="USD", cover_fees=False,
            )

    def test_negative_tip_rejected(self):
        with pytest.raises(ValueError):
            DonorTipBreakdown.compute(
                donation=Decimal("10.00"), tip=Decimal("-1"), currency="USD", cover_fees=False,
            )

    def test_rate_at_or_above_one_rejected(self):
        with pytest.raises(ValueError):
            DonorTipBreakdown.compute(
                donation=Decimal("10.00"), tip=Decimal("0"), currency="USD",
                cover_fees=True, processing_fee_rate=Decimal("1.0"),
            )

    def test_application_fee_must_equal_tip_invariant(self):
        with pytest.raises(ValueError):
            DonorTipBreakdown(
                currency="usd", donation=Decimal("100.00"), tip=Decimal("10.00"),
                fee_coverage=Decimal("0.00"), total=Decimal("110.00"),
                application_fee=Decimal("5.00"),  # != tip → invariant violation
                org_net=Decimal("100.00"), cover_fees=False,
            )

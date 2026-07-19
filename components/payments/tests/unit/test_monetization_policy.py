"""Donation-monetization policy — pure domain rules (P5).

No DB, no framework. Locks the one rule that matters: each mode's donor-tip
behaviour, that the modes are mutually exclusive (only `tip` collects a tip),
and that an unknown/empty mode falls back to the current live default (tip).
"""
from __future__ import annotations

from components.payments.domain.policies.monetization_policy import (
    NoFeePolicy,
    RevenueSharePolicy,
    TipPolicy,
    collects_donor_tip,
    policy_for_mode,
)


class TestPolicyForMode:
    def test_tip_mode_resolves_to_tip_policy(self):
        assert isinstance(policy_for_mode("tip"), TipPolicy)

    def test_none_mode_resolves_to_no_fee_policy(self):
        assert isinstance(policy_for_mode("none"), NoFeePolicy)

    def test_revenue_share_mode_resolves_to_revenue_share_policy(self):
        assert isinstance(policy_for_mode("revenue_share"), RevenueSharePolicy)

    def test_unknown_mode_falls_back_to_tip(self):
        assert isinstance(policy_for_mode("wat"), TipPolicy)

    def test_none_value_falls_back_to_tip(self):
        assert isinstance(policy_for_mode(None), TipPolicy)


class TestCollectsDonorTip:
    def test_only_tip_mode_collects_a_donor_tip(self):
        assert collects_donor_tip("tip") is True
        assert collects_donor_tip("none") is False
        assert collects_donor_tip("revenue_share") is False

    def test_unset_mode_defaults_to_collecting_tip(self):
        # Preserves current live behaviour when the field is unset/None.
        assert collects_donor_tip(None) is True
        assert collects_donor_tip("") is True

    def test_modes_are_mutually_exclusive_never_tip_plus_revenue_share(self):
        # revenue_share takes a % instead of a tip — never both on one gift.
        assert RevenueSharePolicy().collects_donor_tip() is False
        assert TipPolicy().collects_donor_tip() is True


# ── Flat-% application-fee rate by mode (bps — the single source) ───────────
from components.payments.domain.policies.monetization_policy import (  # noqa: E402
    platform_fee_bps_for,
)


class TestPlatformFeeBpsByMode:
    """Each mode is the SINGLE source of its own Connect application-fee rate —
    never a % cut on top of a tip."""

    def test_revenue_share_returns_the_configured_rate(self):
        assert RevenueSharePolicy().platform_fee_bps(300) == 300
        assert RevenueSharePolicy().platform_fee_bps(250) == 250

    def test_tip_mode_takes_no_percentage_cut(self):
        # The tip IS the fee (handled separately) — 0 bps, never a % on top.
        assert TipPolicy().platform_fee_bps(300) == 0

    def test_none_mode_takes_nothing(self):
        assert NoFeePolicy().platform_fee_bps(300) == 0

    def test_revenue_share_clamps_negative_or_missing_to_zero(self):
        assert RevenueSharePolicy().platform_fee_bps(0) == 0
        assert RevenueSharePolicy().platform_fee_bps(-50) == 0

    def test_convenience_resolves_by_mode(self):
        assert platform_fee_bps_for("revenue_share", 300) == 300
        assert platform_fee_bps_for("tip", 300) == 0
        assert platform_fee_bps_for("none", 300) == 0
        # Unknown/unset mode → tip default → no % cut (never silently skims).
        assert platform_fee_bps_for(None, 300) == 0
        assert platform_fee_bps_for("wat", 300) == 0

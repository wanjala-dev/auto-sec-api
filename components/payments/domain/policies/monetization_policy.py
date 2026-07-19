"""Donation-monetization policy — the donation-monetization axis (pure domain).

No Django, no Stripe. Encodes the one business rule that matters here: how the
platform earns on donations a workspace moves, and — critically — that the
modes are MUTUALLY EXCLUSIVE. A donor tip and a revenue-share cut never both
apply to a single gift (that would be charging twice for the same value).

Modes (mirror ``Workspace.donation_monetization``):

* ``tip``           — voluntary donor tip, taken as a Stripe Connect
                      ``application_fee`` on top of the gift; the org keeps its
                      full donation. The platform takes NO percentage cut.
                      Current live default.
* ``revenue_share`` — a FLAT percentage of each donation (``platform_fee_bps``),
                      taken as the Connect ``application_fee``. The platform
                      takes the % instead of a tip, so it collects NO donor tip.
                      (Market-standard shape — Donorbox/Givebutter take a flat %;
                      a paid plan tier can later "buy the % down". A volume-
                      threshold / per-charge-marginal model was researched and
                      rejected: no peer offers it and it adds disproportionate
                      money-path complexity. See MONETIZATION_REVENUE_SHARE_PLAN.)
* ``none``          — no platform cut on donations (e.g. a for-profit or an
                      explicitly opted-out workspace).

The Stripe adapter consumes a single basis-points value (``application_fee_percent``
for subscriptions, ``application_fee_amount`` = bps × amount for one-time). This
policy is the SINGLE SOURCE of that bps by mode — so the modes stay mutually
exclusive (tip → 0 bps + a tip; revenue_share → the rate + no tip; none → 0).
"""
from __future__ import annotations

import abc

# Mode constants — mirror Workspace.DONATION_MONETIZATION_* (kept here too so
# the domain has no dependency on the persistence layer).
MODE_TIP = "tip"
MODE_REVENUE_SHARE = "revenue_share"
MODE_NONE = "none"


class MonetizationPolicy(abc.ABC):
    """Strategy for one donation-monetization mode."""

    mode: str

    @abc.abstractmethod
    def collects_donor_tip(self) -> bool:
        """Whether a voluntary donor tip is collected under this mode."""
        ...

    @abc.abstractmethod
    def platform_fee_bps(self, configured_bps: int = 0) -> int:
        """The Connect ``application_fee`` rate (basis points) for this mode.

        Single source of the donation fee rate so the modes are mutually
        exclusive — each mode returns only its own rate (never a % cut on top of
        a tip). ``configured_bps`` is the workspace's configured revenue-share
        rate; only ``revenue_share`` honours it.
        """
        ...


class TipPolicy(MonetizationPolicy):
    """Donor-tip monetization (current live default)."""

    mode = MODE_TIP

    def collects_donor_tip(self) -> bool:
        return True

    def platform_fee_bps(self, configured_bps: int = 0) -> int:
        # The fee is the donor's voluntary tip (handled separately) — no % cut.
        return 0


class NoFeePolicy(MonetizationPolicy):
    """No platform cut on donations."""

    mode = MODE_NONE

    def collects_donor_tip(self) -> bool:
        return False

    def platform_fee_bps(self, configured_bps: int = 0) -> int:
        # The org keeps 100% — no tip, no cut.
        return 0


class RevenueSharePolicy(MonetizationPolicy):
    """Flat percentage cut of each donation (basis points).

    Collects NO donor tip — revenue share XOR tipping; the platform's take is
    the flat percentage, never also a tip on the same gift.
    """

    mode = MODE_REVENUE_SHARE

    def collects_donor_tip(self) -> bool:
        return False

    def platform_fee_bps(self, configured_bps: int = 0) -> int:
        # The fee is the configured flat rate — never a tip.
        return max(0, int(configured_bps or 0))


_POLICY_BY_MODE: dict[str, type[MonetizationPolicy]] = {
    MODE_TIP: TipPolicy,
    MODE_REVENUE_SHARE: RevenueSharePolicy,
    MODE_NONE: NoFeePolicy,
}


def policy_for_mode(mode: str | None) -> MonetizationPolicy:
    """Resolve the policy for a donation-monetization mode.

    An unknown / empty mode falls back to :class:`TipPolicy` — the current
    live default — so a missing value can never silently apply a % cut.
    """
    return _POLICY_BY_MODE.get((mode or MODE_TIP), TipPolicy)()


def collects_donor_tip(mode: str | None) -> bool:
    """Convenience: does this monetization mode collect a donor tip?"""
    return policy_for_mode(mode).collects_donor_tip()


def platform_fee_bps_for(mode: str | None, configured_bps: int = 0) -> int:
    """Convenience: the Connect application-fee rate (bps) for a mode + config."""
    return policy_for_mode(mode).platform_fee_bps(configured_bps)

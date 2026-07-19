"""Donor-tip money math (pure domain — no Django, no Stripe).

A donor tip is an OPTIONAL extra amount a donor adds at checkout, on top of
their donation, that goes to the PLATFORM instead of the charity. It is the
adoption lever in the monetization model (see
``docs/plans/MONETIZATION_REVENUE_SHARE_PLAN.md`` and
``docs/plans/DONOR_TIPS_IMPLEMENTATION.md``): the platform stays free to the
nonprofit, the donor optionally funds it.

Two donor-side add-ons are bundled here and MUST be kept distinct:

  (a) fee_coverage  — the donor covers the payment processor's fee so the org
                      receives its FULL donation. NOT platform revenue.
  (b) tip           — a voluntary contribution to the platform. THIS is revenue.

This module is the single source of truth for the arithmetic, because getting
it wrong means either the org is short-changed or a donor is over-charged —
both unacceptable on the money path.

Charge model assumption: **Stripe Connect *direct* charges** (the current
architecture — the checkout passes ``stripe_account=<connected account>``).
In a direct charge:

  * the charge total ``T`` is created on the connected (org) account,
  * the processor fee ``r*T + f`` is borne by the connected account,
  * the platform ``application_fee`` ``A`` is transferred to the platform in
    full (the platform does not separately pay processor fees on it).

So org_net = T - (r*T + f) - A, and platform_net = A.

We always set ``A = tip`` (the platform's take is exactly the tip — never a
silent cut). The gross-up only changes ``T`` so the org nets what it should.

  * cover_fees = True:  org nets exactly the donation.
        T = (donation + tip + f) / (1 - r)
        fee_coverage = T - donation - tip
  * cover_fees = False: org absorbs the processor fee (incl. on the tip).
        T = donation + tip
        fee_coverage = 0

Rounding: the grossed-up total is rounded UP to the currency's minor unit so
the org is never left a cent short; tip and donation are donor-/caller-exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


# Currencies Stripe treats as zero-decimal would need special handling; the
# platform operates in 2-decimal currencies (USD/EUR/GBP/etc.) today, so we
# quantize to cents. If a zero-decimal currency (JPY, etc.) is ever added,
# this exponent must become currency-aware — flagged so it isn't silent.
_CENTS = Decimal("0.01")


def _round_up(value: Decimal) -> Decimal:
    """Round up to the minor unit so the org is never short a cent."""
    return value.quantize(_CENTS, rounding=ROUND_CEILING)


def _round_half(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DonorTipRequest:
    """A donor's tip choice at checkout, threaded into the gateway.

    ``tip`` is the voluntary amount the donor adds for the platform (0 = no
    tip). ``cover_fees`` is whether the donor also covers the processor fee so
    the org receives its full donation. The adapter turns this into a
    :class:`DonorTipBreakdown` using the provider's fee config.
    """

    tip: Decimal
    cover_fees: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tip", Decimal(self.tip))
        if self.tip < 0:
            raise ValueError("DonorTipRequest.tip cannot be negative.")

    @property
    def is_active(self) -> bool:
        return self.tip > 0


@dataclass(frozen=True)
class DonorTipBreakdown:
    """The fully-resolved amounts for a donation that carries a donor tip.

    All amounts are positive ``Decimal`` values in ``currency``'s major unit
    (e.g. dollars, not cents). ``application_fee`` is what the platform takes
    and equals ``tip`` exactly. ``org_net`` is what the connected account
    keeps AFTER the processor fee and the application fee.
    """

    currency: str
    donation: Decimal
    tip: Decimal
    fee_coverage: Decimal
    total: Decimal
    application_fee: Decimal
    org_net: Decimal
    cover_fees: bool

    def __post_init__(self) -> None:
        for name in ("donation", "tip", "fee_coverage", "total", "application_fee", "org_net"):
            if getattr(self, name) < 0:
                raise ValueError(f"DonorTipBreakdown.{name} must be non-negative.")
        if self.donation <= 0:
            raise ValueError("DonorTipBreakdown.donation must be greater than zero.")
        # The platform's take is ALWAYS exactly the tip — never a hidden cut.
        if self.application_fee != self.tip:
            raise ValueError("DonorTipBreakdown.application_fee must equal the tip.")

    @property
    def has_tip(self) -> bool:
        return self.tip > 0

    @classmethod
    def compute(
        cls,
        *,
        donation: Decimal,
        tip: Decimal,
        currency: str,
        cover_fees: bool,
        processing_fee_rate: Decimal = Decimal("0"),
        processing_fee_fixed: Decimal = Decimal("0"),
    ) -> "DonorTipBreakdown":
        """Resolve the charge breakdown for a donation + optional tip.

        ``donation`` is the donor's intended gift to the org. ``tip`` is the
        voluntary platform contribution (0 = no tip). ``processing_fee_rate``
        (e.g. ``Decimal("0.029")``) and ``processing_fee_fixed`` (e.g.
        ``Decimal("0.30")``) describe the processor's fee and are injected by
        the caller — never hard-coded here, because they vary per provider and
        per account (Stripe nonprofit pricing differs from standard).
        """
        donation = Decimal(donation)
        tip = Decimal(tip)
        rate = Decimal(processing_fee_rate)
        fixed = Decimal(processing_fee_fixed)

        if donation <= 0:
            raise ValueError("donation must be greater than zero.")
        if tip < 0:
            raise ValueError("tip cannot be negative.")
        if rate < 0 or rate >= 1:
            raise ValueError("processing_fee_rate must be in [0, 1).")
        if fixed < 0:
            raise ValueError("processing_fee_fixed cannot be negative.")

        donation = _round_half(donation)
        tip = _round_half(tip)

        if cover_fees:
            # Gross up so org nets the full donation after fee + application fee.
            total = _round_up((donation + tip + fixed) / (Decimal("1") - rate))
            fee_coverage = total - donation - tip
            # Defensive: rounding up can only ever make org_net >= donation.
            if fee_coverage < 0:
                fee_coverage = Decimal("0.00")
        else:
            total = _round_half(donation + tip)
            fee_coverage = Decimal("0.00")

        processor_fee = _round_half(rate * total + fixed)
        org_net = total - processor_fee - tip

        return cls(
            currency=str(currency).strip().lower(),
            donation=donation,
            tip=tip,
            fee_coverage=fee_coverage,
            total=total,
            application_fee=tip,
            org_net=org_net,
            cover_fees=cover_fees,
        )

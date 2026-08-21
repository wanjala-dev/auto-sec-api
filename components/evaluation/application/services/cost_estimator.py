"""What a run will cost, stated before it is started (ADR 0033 D7).

The same principle as the model picker: a spend decision is presented with its
price, before the click, not discovered on next month's bill. An eval run is
N cases x (agent call + judge call), and on a large suite with an expensive
model that is real money.

This is an ESTIMATE and says so. The assumptions travel with the number in the
API payload and are rendered — an estimate whose basis is invisible is a guess
with a currency symbol, and an operator who cannot see the assumption cannot
tell when it stops holding.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Rough per-call token shape. Deliberately round numbers: pretending to
#: three significant figures would imply a precision this cannot have.
_ASSUMED_INPUT_TOKENS_PER_CALL = 2000
_ASSUMED_OUTPUT_TOKENS_PER_CALL = 600
#: One agent call + one judge call per case, at minimum.
_CALLS_PER_CASE = 2

ASSUMPTIONS = (
    f"≈{_CALLS_PER_CASE} LLM calls per case (agent + judge), "
    f"≈{_ASSUMED_INPUT_TOKENS_PER_CALL} input and {_ASSUMED_OUTPUT_TOKENS_PER_CALL} output tokens each, "
    "priced from the model catalogue. Actual cost varies with case size and how "
    "many tool calls the agent makes."
)


@dataclass(frozen=True)
class CostEstimate:
    cases: int
    model_slug: str
    estimated_cost_usd: Decimal
    cap_usd: Decimal | None
    assumptions: str = ASSUMPTIONS

    @property
    def within_cap(self) -> bool:
        if self.cap_usd is None:
            return True
        return self.estimated_cost_usd <= self.cap_usd

    def as_dict(self) -> dict:
        return {
            "cases": self.cases,
            "model_slug": self.model_slug,
            "estimated_cost_usd": f"{self.estimated_cost_usd:.4f}",
            "cap_usd": f"{self.cap_usd:.2f}" if self.cap_usd is not None else None,
            "within_cap": self.within_cap,
            "assumptions": self.assumptions,
        }


def estimate_run_cost(
    *, cases: int, model_slug: str, cap_usd: Decimal | None = None, model_lookup=None
) -> CostEstimate:
    """Estimate a run's cost from the catalogue price of ``model_slug``.

    An unknown model yields a **zero** estimate rather than a guess, and the
    caller renders that as "price not in catalogue" (the model picker does the
    same). Inventing a number for a model we have no price for would be the
    over-claim this codebase keeps removing.
    """
    input_price, output_price = _prices_for(model_lookup, model_slug)

    per_call = input_price * Decimal(_ASSUMED_INPUT_TOKENS_PER_CALL) / Decimal(1000) + output_price * Decimal(
        _ASSUMED_OUTPUT_TOKENS_PER_CALL
    ) / Decimal(1000)
    total = per_call * Decimal(_CALLS_PER_CASE) * Decimal(max(cases, 0))

    return CostEstimate(
        cases=max(cases, 0),
        model_slug=model_slug,
        estimated_cost_usd=total.quantize(Decimal("0.000001")),
        cap_usd=cap_usd,
    )


def _prices_for(model_lookup, model_slug: str) -> tuple[Decimal, Decimal]:
    """Prices come from an injected lookup — the application layer stays ORM-free.

    `test_application_layer_purity` refuses an ORM import here, and it is right
    to: a service that reaches into persistence cannot be exercised without a
    database, and this one is pure arithmetic over two numbers.

    No lookup, or a model the catalogue does not price, yields ZERO rather than
    a guess. The caller renders that as "price not in catalogue", exactly as the
    model picker does. Inventing a number for a model we have no price for would
    be the over-claim this codebase keeps removing.
    """
    if model_lookup is None:
        return Decimal(0), Decimal(0)
    found = model_lookup(model_slug)
    if not found:
        return Decimal(0), Decimal(0)
    return Decimal(str(found[0])), Decimal(str(found[1]))


__all__ = ["ASSUMPTIONS", "CostEstimate", "estimate_run_cost"]

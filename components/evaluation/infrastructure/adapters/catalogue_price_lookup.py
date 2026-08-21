"""Catalogue prices for the cost estimator (ADR 0033 D7).

The ORM read lives here rather than in the application service because the
application layer must be ORM-free — `test_application_layer_purity` enforces
it, and the practical benefit is that `estimate_run_cost` is pure arithmetic
that can be tested without a database.

An unknown model returns ``None``, which the estimator turns into a zero
estimate rather than a guess.
"""

from __future__ import annotations


def catalogue_price_lookup(model_slug: str):
    """``(input_per_1k, output_per_1k)`` for a model, or ``None``."""
    from infrastructure.persistence.ai.llms.models import AIModel

    row = (
        AIModel.objects.filter(slug=model_slug)
        .values("input_cost_per_1k", "output_cost_per_1k")
        .first()
    )
    if not row:
        return None
    return (row["input_cost_per_1k"] or 0, row["output_cost_per_1k"] or 0)


__all__ = ["catalogue_price_lookup"]

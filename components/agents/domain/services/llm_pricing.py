"""Price a run from the tokens it already recorded.

The worker telemetry has always captured ``model``, ``input_tokens``,
``output_tokens`` and ``llm_calls`` per run — but ``cost_usd`` is written as
``null`` and never computed. Measured 2026-08-13: across 416 runs carrying
``run_metadata``, ``cost_usd_total > 0`` in **zero** of them. So the surfaced
"$0.00" was never "this run was cheap"; it was "nobody multiplied". Cost is not
missing data here — it is a missing multiplication.

## Why this table carries a version, and why that is the whole point

A hardcoded price map is the classic silently-rotting guard: prices change, the
map does not, and it keeps returning confident numbers that are quietly wrong.
Nothing in the output would say so.

So every priced figure records WHICH table produced it (``PRICE_TABLE_VERSION``),
exactly as ``PatchAttestation`` records ``policy_version``. A stale price then
becomes a visible fact — you can filter for it, re-price it, or discount it —
rather than an invisible drift. **If you edit a price, bump the version in the
same commit.** A changed number under an unchanged version is worse than no
number, because it is unfalsifiable.

## What is deliberately NOT done

Old runs are NOT back-filled. Pricing a run from months ago with today's table
would attach a number that was never true, and the version stamp would say it
was current. Historical runs keep ``cost_usd = None`` and report
``priced = False`` — honest, and it makes the cutover visible in the data.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump in the SAME COMMIT as any price edit. Consumers store this alongside the
#: computed figure so a stale price is queryable, not invisible.
PRICE_TABLE_VERSION = "2026-08-13"

#: USD per 1M tokens, (input, output). Sourced from published list prices on the
#: date above. Keys are matched by PREFIX (see :func:`_lookup`) because providers
#: append dated suffixes — "gpt-4o-mini-2024-07-18" must price as "gpt-4o-mini"
#: without needing a new row every time a snapshot ships.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1-mini": (1.10, 4.40),
    "o1": (15.00, 60.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


@dataclass(frozen=True)
class RunCost:
    """What a run cost, and whether we can honestly say so."""

    #: None when the model is unknown to this table — NOT 0.0. A zero would read
    #: as a measurement; None reads as "not priced", which is the truth.
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    llm_calls: int
    #: Distinct model ids seen in the run, for display and for spotting a run
    #: that unexpectedly used an expensive model.
    models: tuple[str, ...]
    #: False when ANY component model was unpriceable — a partial total would
    #: understate the run, so the whole figure is withheld rather than shaded.
    priced: bool
    price_table_version: str


def _lookup(model: str) -> tuple[float, float] | None:
    """Longest-prefix match, so dated snapshots inherit their family's price."""
    name = (model or "").strip().lower()
    if not name:
        return None
    best: tuple[float, float] | None = None
    best_len = -1
    for prefix, price in _PRICES_PER_MTOK.items():
        if name.startswith(prefix) and len(prefix) > best_len:
            best, best_len = price, len(prefix)
    return best


def price_run(cost_records: object) -> RunCost:
    """Total a run's ``run_metadata.cost_usd_records``.

    Accepts the shape the telemetry actually writes — a DICT keyed by an opaque
    id, values holding ``model`` / ``input_tokens`` / ``output_tokens`` /
    ``llm_calls``. A list of the same value-shape is also accepted, because an
    earlier writer used one and old rows survive. Anything else totals to zero
    rather than raising: this feeds a read endpoint over 1,884 historical runs,
    and one malformed row must not take out the list.
    """
    if isinstance(cost_records, dict):
        entries = list(cost_records.values())
    elif isinstance(cost_records, (list, tuple)):
        entries = list(cost_records)
    else:
        entries = []

    total = 0.0
    in_tok = out_tok = calls = 0
    models: list[str] = []
    priced = True
    saw_tokens = False

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model = str(entry.get("model") or "")
        if model and model not in models:
            models.append(model)
        try:
            e_in = int(entry.get("input_tokens") or 0)
            e_out = int(entry.get("output_tokens") or 0)
            calls += int(entry.get("llm_calls") or 0)
        except (TypeError, ValueError):
            continue
        in_tok += e_in
        out_tok += e_out
        if e_in or e_out:
            saw_tokens = True

        price = _lookup(model)
        if price is None:
            # Unknown model: we cannot price this component, so the run's total
            # is not trustworthy. Say so rather than quietly under-reporting.
            priced = False
            continue
        total += (e_in / 1_000_000.0) * price[0] + (e_out / 1_000_000.0) * price[1]

    return RunCost(
        cost_usd=round(total, 6) if (priced and saw_tokens) else None,
        input_tokens=in_tok,
        output_tokens=out_tok,
        llm_calls=calls,
        models=tuple(models),
        priced=priced and saw_tokens,
        price_table_version=PRICE_TABLE_VERSION,
    )

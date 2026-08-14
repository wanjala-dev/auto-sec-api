"""Pricing a run from the tokens it already recorded (Tom gap #5).

The bug this exists for, measured 2026-08-13: across 416 runs carrying
``run_metadata``, ``cost_usd_total > 0`` in ZERO of them. The telemetry writes
``cost_usd: null`` on every record while faithfully capturing model + tokens, so
the surfaced "$0.00" was a blank wearing a number's clothes.
"""

import pytest

from components.agents.domain.services.llm_pricing import (
    PRICE_TABLE_VERSION,
    price_run,
)

pytestmark = pytest.mark.unit


def _rec(model="gpt-4o-mini-2024-07-18", i=4070, o=617, calls=2):
    return {"model": model, "source": "worker_telemetry", "cost_usd": None,
            "llm_calls": calls, "input_tokens": i, "output_tokens": o}


class TestPricesTheRealTelemetryShape:
    def test_dict_keyed_by_id_is_the_shape_that_ships(self):
        """The live shape. An earlier cut assumed a LIST and would have returned
        zeros for every run in production while passing its own tests."""
        out = price_run({"f7fafb92-9a64-49fc-a410-8d307e62c907": _rec()})

        assert out.input_tokens == 4070
        assert out.output_tokens == 617
        assert out.llm_calls == 2
        assert out.priced is True
        # input 4070/1M * $0.15 = 0.00061  +  output 617/1M * $0.60 = 0.00037
        assert out.cost_usd == pytest.approx(0.000981, abs=1e-6)

    def test_dated_snapshot_prices_as_its_family(self):
        """Providers append dated suffixes. Requiring an exact key would mean a
        new row per snapshot, and an unpriced run every time one shipped."""
        assert price_run({"a": _rec(model="gpt-4o-mini-2024-07-18")}).priced is True

    def test_a_list_of_records_still_works(self):
        """An earlier writer used a list; those rows survive."""
        assert price_run([_rec()]).cost_usd == price_run({"x": _rec()}).cost_usd

    def test_longest_prefix_wins(self):
        """'gpt-4o-mini' must not be priced as 'gpt-4o' — a 16x difference."""
        mini = price_run({"a": _rec(model="gpt-4o-mini", i=1_000_000, o=0)}).cost_usd
        full = price_run({"a": _rec(model="gpt-4o", i=1_000_000, o=0)}).cost_usd
        assert mini == pytest.approx(0.15)
        assert full == pytest.approx(2.50)


class TestRefusesToInventANumber:
    def test_unknown_model_is_unpriced_not_zero(self):
        """The whole point. A 0.0 reads as 'this was free'; None reads as 'we did
        not price it', which is what is true."""
        out = price_run({"a": _rec(model="some-new-model-v9")})

        assert out.cost_usd is None
        assert out.priced is False
        assert out.input_tokens == 4070  # tokens are still real and still reported

    def test_one_unknown_model_withholds_the_whole_total(self):
        """A partial total understates the run. Better to say 'not priced' than to
        quietly bill half of it."""
        out = price_run({"a": _rec(), "b": _rec(model="mystery-model")})

        assert out.priced is False
        assert out.cost_usd is None

    def test_no_tokens_is_unpriced(self):
        assert price_run({"a": _rec(i=0, o=0)}).priced is False

    @pytest.mark.parametrize("junk", [None, "records", 42, {"a": "not-a-dict"}, []])
    def test_malformed_input_never_raises(self, junk):
        """This feeds a read endpoint over 1,884 historical runs. One bad row must
        not take out the list."""
        out = price_run(junk)

        assert out.cost_usd is None
        assert out.input_tokens == 0


class TestTheVersionStampIsTheAntiRotGuard:
    def test_every_result_carries_the_table_version(self):
        """A hardcoded price map rots silently — prices change, the map does not,
        and it keeps returning confident wrong numbers. Stamping which table
        produced a figure makes staleness queryable instead of invisible. Same
        principle as PatchAttestation.policy_version."""
        assert price_run({"a": _rec()}).price_table_version == PRICE_TABLE_VERSION
        assert price_run(None).price_table_version == PRICE_TABLE_VERSION

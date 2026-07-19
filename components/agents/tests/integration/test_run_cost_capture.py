"""Cost-capture write path against real pricing rows (task #46).

Real DB. Pins the honest half of the cost cap: tokens are priced against the
seeded ``AIModel`` rates exactly like the planner instrumentation, unknown
models are ``None`` (never a fabricated $0.00), and the planner's
``DeepRunLog`` ``llm_call`` rows aggregate into the runner's seed record.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from components.agents.infrastructure.adapters.langchain.deep.costing import (
    cost_usd_for_tokens,
    planner_cost_record,
    worker_cost_record,
)
from infrastructure.persistence.ai.agents.models import DeepRun, DeepRunLog
from infrastructure.persistence.ai.llms.models import AIModel, AIModelProvider


def _seed_model(model_id="gpt-4o-mini", input_per_1k="0.000150", output_per_1k="0.000600"):
    provider = AIModelProvider.objects.create(slug="openai-test", name="OpenAI")
    return AIModel.objects.create(
        slug=f"{model_id}-slug",
        name=model_id,
        provider=provider,
        model_id=model_id,
        input_cost_per_1k=Decimal(input_per_1k),
        output_cost_per_1k=Decimal(output_per_1k),
    )


@pytest.mark.django_db
class TestCostForTokens:
    def test_prices_against_seeded_rates(self):
        _seed_model()
        # 2000 in @ 0.00015/1k + 1000 out @ 0.0006/1k = 0.0003 + 0.0006
        assert cost_usd_for_tokens("gpt-4o-mini", 2000, 1000) == pytest.approx(0.0009)

    def test_unknown_model_is_none_not_zero(self):
        assert cost_usd_for_tokens("model-nobody-seeded", 2000, 1000) is None

    def test_zero_tokens_is_none(self):
        _seed_model()
        assert cost_usd_for_tokens("gpt-4o-mini", 0, 0) is None


@pytest.mark.django_db
class TestWorkerCostRecordRealPricing:
    def test_end_to_end_pricing_from_telemetry(self):
        _seed_model()
        record = worker_cost_record(
            {
                "success": True,
                "telemetry": {
                    "tokens": {"input_tokens": 2000, "output_tokens": 1000, "total_tokens": 3000},
                    "models": {"gpt-4o-mini": 2},
                    "llm_calls": 2,
                },
            }
        )
        assert record["cost_usd"] == pytest.approx(0.0009)
        assert record["model"] == "gpt-4o-mini"
        assert record["input_tokens"] == 2000


@pytest.mark.django_db
class TestPlannerCostRecord:
    def _run(self, user_factory, thread_id="thread-pcr"):
        user = user_factory()
        return DeepRun.objects.create(thread_id=thread_id, plan_id="plan-pcr", user=user)

    def test_aggregates_planner_llm_call_rows(self, user_factory):
        run = self._run(user_factory)
        for cost, p, c in ((Decimal("0.001"), 500, 100), (Decimal("0.002"), 700, 200)):
            DeepRunLog.objects.create(
                deep_run=run,
                event_type="llm_call",
                agent_type="planner",
                prompt_tokens=p,
                completion_tokens=c,
                cost_usd=cost,
            )
        # A non-planner llm row must not leak into the planner seed.
        DeepRunLog.objects.create(
            deep_run=run, event_type="llm_call", agent_type="worker", prompt_tokens=999, cost_usd=Decimal("9")
        )

        record = planner_cost_record("thread-pcr")

        assert record["cost_usd"] == pytest.approx(0.003)
        assert record["input_tokens"] == 1200
        assert record["output_tokens"] == 300
        assert record["source"] == "planner_llm_call_logs"

    def test_no_rows_is_none(self, user_factory):
        self._run(user_factory, thread_id="thread-empty")
        assert planner_cost_record("thread-empty") is None
        assert planner_cost_record(None) is None

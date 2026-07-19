"""ORM adapter satisfying :class:`DeepRunAggregatorPort`."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum


class OrmDeepRunAggregatorRepository:
    def aggregate_plan_totals(self, *, plan_id: str) -> dict[str, Decimal]:
        from infrastructure.persistence.ai.agents.models import DeepRunLog

        agg = (
            DeepRunLog.objects.filter(plan_id=plan_id)
            .aggregate(
                prompt=Sum("prompt_tokens"),
                completion=Sum("completion_tokens"),
            )
        )
        return {
            "prompt": Decimal(agg.get("prompt") or 0),
            "completion": Decimal(agg.get("completion") or 0),
        }

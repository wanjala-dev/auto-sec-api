"""Response DTOs for the AI quality analytics endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from components.agents.application.ports.ai_analytics_port import (
    AIQualityOverviewView,
    DayMetricView,
    ModelChangeEventView,
    ModelDayMetricView,
)


def _money(value: Decimal) -> str:
    """Serialize cost as a fixed-6-decimal string (JSON floats drift)."""
    return f"{value:.6f}"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _model_dict(model: ModelDayMetricView) -> dict:
    return {
        "model": model.model,
        "llm_calls": model.llm_calls,
        "prompt_tokens": model.prompt_tokens,
        "completion_tokens": model.completion_tokens,
        "cost_usd": _money(model.cost_usd),
        "latency_p50_ms": model.latency_p50_ms,
        "latency_p95_ms": model.latency_p95_ms,
    }


def _day_dict(day: DayMetricView) -> dict:
    return {
        "date": day.date.isoformat(),
        "models": [_model_dict(m) for m in day.models],
        "runs_total": day.runs_total,
        "runs_completed": day.runs_completed,
        "runs_failed": day.runs_failed,
        "assistant_messages": day.assistant_messages,
        "feedback_up": day.feedback_up,
        "feedback_down": day.feedback_down,
    }


def _change_dict(event: ModelChangeEventView) -> dict:
    return {
        "changed_at": event.changed_at.isoformat(),
        "field": event.field,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "changed_by": event.changed_by_id,
    }


@dataclass(frozen=True)
class AIQualityOverviewResource:
    """Serializable dashboard payload: series + totals + annotations."""

    payload: dict = field(default_factory=dict)

    @classmethod
    def from_view(cls, view: AIQualityOverviewView) -> AIQualityOverviewResource:
        totals_by_model: dict[str, dict] = {}
        llm_calls = 0
        cost = Decimal("0")
        runs_total = runs_failed = 0
        assistant_messages = feedback_up = feedback_down = 0

        for day in view.series:
            runs_total += day.runs_total
            runs_failed += day.runs_failed
            assistant_messages += day.assistant_messages
            feedback_up += day.feedback_up
            feedback_down += day.feedback_down
            for model in day.models:
                llm_calls += model.llm_calls
                cost += model.cost_usd
                bucket = totals_by_model.setdefault(
                    model.model,
                    {"model": model.model, "llm_calls": 0, "cost_usd": Decimal("0")},
                )
                bucket["llm_calls"] += model.llm_calls
                bucket["cost_usd"] += model.cost_usd

        feedback_total = feedback_up + feedback_down
        by_model = [
            {**bucket, "cost_usd": _money(bucket["cost_usd"])}
            for bucket in sorted(totals_by_model.values(), key=lambda b: b["llm_calls"], reverse=True)
        ]

        return cls(
            payload={
                "workspace_id": view.workspace_id,
                "window_days": view.window_days,
                "series": [_day_dict(day) for day in view.series],
                "totals": {
                    "llm_calls": llm_calls,
                    "cost_usd": _money(cost),
                    "runs_total": runs_total,
                    "runs_failed": runs_failed,
                    "failure_rate": _ratio(runs_failed, runs_total),
                    "assistant_messages": assistant_messages,
                    "feedback_up": feedback_up,
                    "feedback_down": feedback_down,
                    "positive_ratio": _ratio(feedback_up, feedback_total),
                    "feedback_rate": _ratio(feedback_total, assistant_messages),
                    "by_model": by_model,
                },
                "model_changes": [_change_dict(e) for e in view.model_changes],
            }
        )

    def to_dict(self) -> dict:
        return self.payload

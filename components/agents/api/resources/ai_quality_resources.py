"""Response DTOs for the AI quality analytics endpoint.

ADR 0032 D3 + D4 govern every number that leaves here:

* **No bare rate is the headline.** ``totals.rates`` carries each decision-
  driving rate as a ``MeasuredRate`` — a state, the numerator, the DENOMINATOR,
  and 95% Wilson bounds. "3 of 4 = 75%" is the failure mode this exists to
  prevent.
* **Absence is a distinct state, never green.** ``coverage.state`` and each
  ``series[].state`` say ``no_data`` when nothing ran. A zero-height bar on a
  day nothing happened must not read as "no failures" — that is #415's lesson
  ("an empty report must not read as a clean one") applied to AI.
* **What was dropped is stated.** ``excluded`` reports runs the rollup could not
  attribute to any workspace, rather than absorbing them into a quiet
  under-count.

``totals.failure_rate`` / ``totals.positive_ratio`` are RETAINED as bare
ratios purely for contract stability with existing callers. They are not the
headline and no surface should render them alone — use ``totals.rates``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from components.agents.application.ports.ai_analytics_port import (
    AIQualityOverviewView,
    DayMetricView,
    ModelChangeEventView,
    ModelDayMetricView,
)
from components.shared_kernel.domain.measured_rate import (
    STATE_MEASURED,
    STATE_NO_DATA,
    measure_rate,
)

#: Floor before a run-based rate may be called ``measured``. Same value and
#: same reasoning as ``fix_confidence.AUTOFIX_MIN_TRIALS``: the Wilson bound
#: already punishes small n, but a hard floor lets the copy say the true reason
#: ("4 runs") instead of an abstract score an operator cannot act on.
MIN_RUNS_FOR_RATE = 10

#: Floor before a thumbs rate may be called ``measured``. Explicit feedback is
#: sparse and negatively biased, so a handful of votes is never a quality
#: signal (ADR 0032 D2).
MIN_VOTES_FOR_RATE = 10


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


def _day_had_activity(day: DayMetricView) -> bool:
    return bool(day.models) or day.runs_total > 0 or day.assistant_messages > 0


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
        # The repository emits zero-activity days so the axis is continuous.
        # Without this flag the frontend cannot tell "0 failures out of 40 runs"
        # from "nothing ran", and a flat green line is the wrong reading of the
        # second one (ADR 0032 D4).
        "state": STATE_MEASURED if _day_had_activity(day) else STATE_NO_DATA,
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

        days_with_activity = sum(1 for day in view.series if _day_had_activity(day))

        # The gate that stops the whole panel reading green on an empty window.
        # A workspace with no runs has no failure rate, no positive ratio and no
        # cost — and "0.0" for each of those is a claim we have not earned.
        coverage = {
            "state": STATE_MEASURED if runs_total or llm_calls or assistant_messages else STATE_NO_DATA,
            "runs_total": runs_total,
            "llm_calls": llm_calls,
            "days_with_activity": days_with_activity,
            "window_days": view.window_days,
            "summary": (
                f"{runs_total} runs over {days_with_activity} of {view.window_days} days"
                if runs_total or llm_calls or assistant_messages
                else f"Not measured — no AI activity in the last {view.window_days} days"
            ),
        }

        # Every decision-driving rate, bounded and carrying n (D3). Failure is
        # reported against runs; the positive ratio against VOTES, not messages,
        # because the denominator an operator would assume is the wrong one.
        rates = {
            "failure": measure_rate(
                runs_failed,
                runs_total,
                min_trials=MIN_RUNS_FOR_RATE,
                noun="runs",
                event="failed",
            ).as_dict(),
            "feedback_positive": measure_rate(
                feedback_up,
                feedback_total,
                min_trials=MIN_VOTES_FOR_RATE,
                noun="votes",
                event="positive",
            ).as_dict(),
        }

        return cls(
            payload={
                "workspace_id": view.workspace_id,
                "window_days": view.window_days,
                "coverage": coverage,
                "series": [_day_dict(day) for day in view.series],
                "totals": {
                    "llm_calls": llm_calls,
                    "cost_usd": _money(cost),
                    "runs_total": runs_total,
                    "runs_failed": runs_failed,
                    # Retained for contract stability. NOT the headline — a bare
                    # ratio with no n is the thing D3 exists to stop. Render
                    # ``rates`` instead.
                    "failure_rate": _ratio(runs_failed, runs_total),
                    "assistant_messages": assistant_messages,
                    "feedback_up": feedback_up,
                    "feedback_down": feedback_down,
                    "positive_ratio": _ratio(feedback_up, feedback_total),
                    "feedback_rate": _ratio(feedback_total, assistant_messages),
                    "by_model": by_model,
                    "rates": rates,
                },
                "excluded": {
                    "unattributed_runs": view.exclusions.unattributed_runs,
                    "sample_rows": view.exclusions.sample_rows,
                    "note": (
                        "Runs with no workspace attribution are counted by no "
                        "workspace's totals; sample data does not enter AI "
                        "quality aggregates."
                    ),
                },
                "model_changes": [_change_dict(e) for e in view.model_changes],
            }
        )

    def to_dict(self) -> dict:
        return self.payload

"""Port for the AI quality analytics read surface.

The dashboard endpoint reads pre-computed daily rollups (written by the
``ai.rollup_ai_quality_daily`` beat task) plus the append-only model
change events — never the raw ``DeepRunLog``. The port returns plain
frozen view dataclasses so the controller and resources stay
framework-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class ModelDayMetricView:
    """One (model, day) rollup bucket."""

    model: str
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_p50_ms: int | None
    latency_p95_ms: int | None


@dataclass(frozen=True)
class DayMetricView:
    """All metrics for one workspace-day: per-model buckets + run/feedback counters."""

    date: date
    models: tuple[ModelDayMetricView, ...] = ()
    runs_total: int = 0
    runs_completed: int = 0
    runs_failed: int = 0
    assistant_messages: int = 0
    feedback_up: int = 0
    feedback_down: int = 0


@dataclass(frozen=True)
class ModelChangeEventView:
    """One model-switch annotation for the dashboard time axis."""

    changed_at: datetime
    field: str
    old_value: str
    new_value: str
    changed_by_id: str | None


@dataclass(frozen=True)
class ExclusionsView:
    """What the aggregate could NOT count, as a number (ADR 0032 D8.3/D8.4).

    An aggregate that quietly drops rows is an aggregate that under-reports
    while looking complete. ``DeepRun.workspace`` is nullable
    (``on_delete=SET_NULL``), so a run whose workspace was deleted — or that was
    never attributed — is invisible to EVERY workspace rollup. The panel states
    the number rather than absorbing it.

    ``unattributed_runs`` counts rows belonging to no workspace at all, which is
    why reporting it on a tenant endpoint discloses no other tenant's data.
    """

    unattributed_runs: int = 0
    sample_rows: int = 0


@dataclass(frozen=True)
class AIQualityOverviewView:
    """The full dashboard payload for one workspace + window."""

    workspace_id: str
    window_days: int
    series: tuple[DayMetricView, ...] = ()
    model_changes: tuple[ModelChangeEventView, ...] = field(default=())
    exclusions: ExclusionsView = field(default_factory=ExclusionsView)


class AIAnalyticsQueryPort(ABC):
    """Read-side port over the AI quality rollup tables."""

    @abstractmethod
    def get_overview(self, workspace_id: str, *, days: int) -> AIQualityOverviewView:
        """Return the day-bucketed metric series + model-change events
        for the trailing ``days`` window (inclusive of today)."""

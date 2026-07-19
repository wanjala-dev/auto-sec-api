"""Application-layer query object for the AI quality analytics overview.

Thin wrapper over ``AIAnalyticsQueryPort`` — mirrors the deep-run
observability queries so the controller depends on the query object and
tests can inject a fake port.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.agents.application.ports.ai_analytics_port import (
    AIAnalyticsQueryPort,
    AIQualityOverviewView,
)

MAX_WINDOW_DAYS = 180
DEFAULT_WINDOW_DAYS = 30


@dataclass
class FetchAIQualityOverviewQuery:
    """Return the rollup series + model-change annotations for a workspace."""

    port: AIAnalyticsQueryPort

    def execute(
        self,
        workspace_id: str,
        *,
        days: int = DEFAULT_WINDOW_DAYS,
    ) -> AIQualityOverviewView:
        clamped = max(1, min(int(days), MAX_WINDOW_DAYS))
        return self.port.get_overview(workspace_id, days=clamped)

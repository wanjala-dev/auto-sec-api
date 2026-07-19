from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamPlanCheckoutRequest:
    plan: str | None
    plan_id: str | int | None = None
    workspace_id: str | None = None
    team_id: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    proration_behavior: str | None = None
    scheme: str | None = None
    site_domain: str | None = None

"""Request DTO for plan change endpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanChangeRequest:
    """Input DTO for plan change request."""
    plan_id: str | int | None = None
    plan: str | int | None = None
    proration_behavior: str | None = None

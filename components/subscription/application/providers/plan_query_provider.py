"""Composition root for the subscription context's plan query service.

Wires the PlanQueryPort to its ORM adapter so consumers never need to
know about the concrete implementation.
"""

from __future__ import annotations

from components.subscription.application.ports.plan_query_port import PlanQueryPort


class PlanQueryProvider:
    """Factory for plan query port instances."""

    def build_plan_query_port(self) -> PlanQueryPort:
        from components.subscription.infrastructure.repositories.plan_query_repository import (
            OrmPlanQueryRepository,
        )

        return OrmPlanQueryRepository()

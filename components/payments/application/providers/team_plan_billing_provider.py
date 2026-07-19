from __future__ import annotations

from components.payments.application.service import (
    TeamPlanBillingService,
)
from components.payments.infrastructure.adapters.checkout_context_adapter import (
    CheckoutContextAdapter,
)
from components.payments.infrastructure.repositories.team_plan_billing_repository import (
    TeamPlanBillingRepository,
)


class TeamPlanBillingProvider:
    """Composition root for workspace team-plan billing workflows."""

    def build_service(self) -> TeamPlanBillingService:
        return TeamPlanBillingService(
            billing_store=TeamPlanBillingRepository(),
            checkout_context=CheckoutContextAdapter(),
        )

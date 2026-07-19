from __future__ import annotations

from components.payments.application.providers.payment_gateway_provider import (
    make_payment_gateway_provider,
)
from components.payments.application.service import (
    TeamPlanPaymentSetupService,
)
from components.payments.infrastructure.repositories.team_plan_payment_setup_repository import (
    TeamPlanPaymentSetupRepository,
)


class TeamPlanPaymentSetupProvider:
    """Composition root for managed team-plan payment setup workflows."""

    def build_service(self) -> TeamPlanPaymentSetupService:
        return TeamPlanPaymentSetupService(
            setup_store=TeamPlanPaymentSetupRepository(
                gateway_provider=make_payment_gateway_provider(),
            ),
        )

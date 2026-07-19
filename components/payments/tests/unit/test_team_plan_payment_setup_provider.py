from __future__ import annotations

from components.payments.application.providers.team_plan_payment_setup_provider import (
    TeamPlanPaymentSetupProvider,
)
from components.payments.application.service import (
    TeamPlanPaymentSetupService,
)


def test_team_plan_payment_setup_provider_builds_service():
    service = TeamPlanPaymentSetupProvider().build_service()

    assert isinstance(service, TeamPlanPaymentSetupService)
    assert service.setup_store.__class__.__name__ == "TeamPlanPaymentSetupRepository"
    assert service.setup_store.gateway_provider.__class__.__name__ == "PaymentGatewayProvider"

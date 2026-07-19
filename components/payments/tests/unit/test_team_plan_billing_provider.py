from __future__ import annotations

from components.payments.application.providers.team_plan_billing_provider import (
    TeamPlanBillingProvider,
)
from components.payments.application.service import (
    TeamPlanBillingService,
)


def test_team_plan_billing_provider_builds_service():
    service = TeamPlanBillingProvider().build_service()

    assert isinstance(service, TeamPlanBillingService)
    assert service.billing_store.__class__.__name__ == "TeamPlanBillingRepository"

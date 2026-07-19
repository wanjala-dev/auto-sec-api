from __future__ import annotations

from components.payments.application.providers.team_plan_webhook_provider import (
    TeamPlanWebhookProvider,
)
from components.payments.application.service import (
    TeamPlanWebhookService,
)


def test_team_plan_webhook_provider_builds_service():
    service = TeamPlanWebhookProvider().build_service()

    assert isinstance(service, TeamPlanWebhookService)
    assert service.webhook_store.__class__.__name__ == "TeamPlanWebhookRepository"
    assert service.webhook_store.payment_transactions.__class__.__name__ == "OrmPaymentTransactionRepository"
    assert (
        service.webhook_store.record_successful_payment_use_case.__class__.__name__
        == "RecordSuccessfulPaymentUseCase"
    )

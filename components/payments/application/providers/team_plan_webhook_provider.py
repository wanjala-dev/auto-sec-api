from __future__ import annotations

from components.payments.application.providers.payment_flow_state_provider import (
    PaymentFlowStateProvider,
)
from components.payments.application.service import TeamPlanWebhookService
from components.payments.application.use_cases.record_successful_payment_use_case import (
    RecordSuccessfulPaymentUseCase,
)
from components.payments.infrastructure.repositories.orm_payment_transaction_repository import (
    OrmPaymentTransactionRepository,
)
from components.payments.infrastructure.repositories.team_plan_webhook_repository import (
    TeamPlanWebhookRepository,
)


class TeamPlanWebhookProvider:
    """Composition root for verified team-plan webhook handling."""

    def build_service(self) -> TeamPlanWebhookService:
        payment_transactions = OrmPaymentTransactionRepository()
        payment_flow_state_provider = PaymentFlowStateProvider()
        return TeamPlanWebhookService(
            webhook_store=TeamPlanWebhookRepository(
                payment_transactions=payment_transactions,
                record_successful_payment_use_case=RecordSuccessfulPaymentUseCase(
                    payment_transactions=payment_transactions,
                    finalize_successful_payment=(
                        payment_flow_state_provider.build_finalize_successful_use_case()
                    ),
                ),
            ),
        )

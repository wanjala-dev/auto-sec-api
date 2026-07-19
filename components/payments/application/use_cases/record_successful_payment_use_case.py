from __future__ import annotations

from decimal import Decimal
from typing import Any

from components.payments.application.use_cases.finalize_successful_payment_use_case import (
    FinalizeSuccessfulPaymentUseCase,
)
from components.payments.application.ports.payment_transaction_store_port import (
    PaymentTransactionStorePort,
)


class RecordSuccessfulPaymentUseCase:
    def __init__(
        self,
        payment_transactions: PaymentTransactionStorePort,
        finalize_successful_payment: FinalizeSuccessfulPaymentUseCase,
    ):
        self.payment_transactions = payment_transactions
        self.finalize_successful_payment = finalize_successful_payment

    def execute(
        self,
        *,
        order: Any | None,
        attempt: Any | None,
        provider: str,
        payment_event: Any | None = None,
        event_type: str | None = None,
        external_id: str | None = None,
        provider_status: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        payload: dict | None = None,
    ) -> None:
        self.payment_transactions.record_transaction(
            order=order,
            attempt=attempt,
            provider=provider,
            status="succeeded",
            payment_event=payment_event,
            event_type=event_type,
            external_id=external_id,
            provider_status=provider_status,
            amount=amount,
            currency=currency,
            payload=payload,
            update_statuses=False,
        )
        self.finalize_successful_payment.execute(
            order=order,
            attempt=attempt,
        )

from __future__ import annotations

from decimal import Decimal

from components.payments.infrastructure.adapters.orders import record_payment_transaction
from components.payments.mappers.db.payment_transaction_mapper import (
    to_payment_transaction_entity,
)
from components.payments.application.ports.payment_transaction_store_port import (
    PaymentTransactionStorePort,
)


class OrmPaymentTransactionRepository(PaymentTransactionStorePort):
    def record_transaction(
        self,
        *,
        order,
        attempt,
        provider: str,
        status: str,
        payment_event=None,
        event_type: str | None = None,
        external_id: str | None = None,
        provider_status: str | None = None,
        amount: Decimal | None = None,
        currency: str | None = None,
        payload: dict | None = None,
        update_statuses: bool = True,
    ):
        transaction = record_payment_transaction(
            order=order,
            attempt=attempt,
            provider=provider,
            status=status,
            payment_event=payment_event,
            event_type=event_type,
            external_id=external_id,
            provider_status=provider_status,
            amount=amount,
            currency=currency,
            payload=payload,
            update_statuses=update_statuses,
        )
        if transaction is None:
            return None
        return to_payment_transaction_entity(transaction)

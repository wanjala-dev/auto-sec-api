from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction as db_transaction

from components.payments.domain.entities.payment_fee_entity import PaymentFeeEntity
from components.payments.mappers.db.payment_fee_mapper import fee_orm_to_entity
from infrastructure.persistence.workspaces.payments.models import PaymentFee

logger = logging.getLogger(__name__)


class OrmPaymentFeeRepository:
    def record_fee(
        self,
        *,
        transaction_id: UUID,
        method_id: UUID,
        provider: str,
        context: str,
        fee_amount: Decimal,
        currency: str,
        fee_percentage: Decimal = Decimal("0"),
        fixed_fee: Decimal = Decimal("0"),
        capped_fee: Decimal | None = None,
        sales_tax_amount: Decimal = Decimal("0"),
        sales_tax_percentage: Decimal = Decimal("0"),
        metadata: dict[str, Any] | None = None,
    ) -> tuple[PaymentFeeEntity, bool]:
        # The unique_payment_fee_transaction_context constraint is the real
        # idempotency guarantee — the handler's read-then-write pre-check is a
        # cheap optimisation that races under acks_late retries / redelivered
        # success events. A duplicate insert raises IntegrityError; we catch it
        # and return the already-recorded fee (created=False) instead of letting
        # it escape. The caller skips downstream side effects (balance debit) on
        # created=False so a replay never double-debits. Wrap in an atomic block
        # so the failed INSERT doesn't poison the outer transaction's state.
        try:
            with db_transaction.atomic():
                row = PaymentFee.objects.create(
                    transaction_id=transaction_id,
                    method_id=method_id,
                    provider=provider,
                    context=context,
                    fee_amount=fee_amount,
                    currency=currency,
                    fee_percentage=fee_percentage,
                    fixed_fee=fixed_fee,
                    capped_fee=capped_fee,
                    sales_tax_amount=sales_tax_amount,
                    sales_tax_percentage=sales_tax_percentage,
                    metadata=metadata or {},
                )
        except IntegrityError:
            existing = PaymentFee.objects.filter(
                transaction_id=transaction_id, context=context
            ).first()
            if existing is None:
                # The constraint that fired wasn't (transaction, context) —
                # surface it rather than swallow an unknown failure.
                raise
            logger.info(
                "payment_fee_already_recorded transaction_id=%s context=%s fee_id=%s",
                transaction_id,
                context,
                existing.id,
            )
            return fee_orm_to_entity(existing), False
        return fee_orm_to_entity(row), True

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone

from components.payments.domain.entities.payment_refund_entity import PaymentRefundEntity
from components.payments.mappers.db.payment_refund_mapper import (
    refund_orm_to_entity,
)
from infrastructure.persistence.workspaces.payments.models import PaymentRefund


class OrmPaymentRefundRepository:
    def create_refund(
        self,
        *,
        transaction_id: UUID,
        attempt_id: UUID,
        provider: str,
        reason: str,
        amount: Decimal,
        currency: str,
        external_id: str = "",
        payment_event_id: UUID | None = None,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PaymentRefundEntity:
        row = PaymentRefund.objects.create(
            transaction_id=transaction_id,
            attempt_id=attempt_id,
            provider=provider,
            reason=reason,
            amount=amount,
            currency=currency,
            external_id=external_id,
            payment_event_id=payment_event_id,
            description=description,
            metadata=metadata or {},
        )
        return refund_orm_to_entity(row)

    def update_refund_status(
        self,
        *,
        refund_id: UUID,
        status: str,
        external_id: str = "",
        failure_reason: str = "",
    ) -> PaymentRefundEntity:
        row = PaymentRefund.objects.get(id=refund_id)
        row.status = status
        update_fields = ["status", "updated_at"]
        if external_id:
            row.external_id = external_id
            update_fields.append("external_id")
        if failure_reason:
            row.failure_reason = failure_reason
            update_fields.append("failure_reason")
        if status in ("succeeded", "failed", "canceled"):
            row.completed_at = timezone.now()
            update_fields.append("completed_at")
        row.save(update_fields=update_fields)
        return refund_orm_to_entity(row)

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentRefundEntity | None:
        row = PaymentRefund.objects.filter(provider=provider, external_id=external_id).first()
        return refund_orm_to_entity(row) if row else None

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_dispute_entity import PaymentDisputeEntity
from components.payments.mappers.db.payment_dispute_mapper import (
    dispute_orm_to_entity,
)
from infrastructure.persistence.workspaces.payments.models import PaymentDispute


class OrmPaymentDisputeRepository:
    def create_dispute(
        self,
        *,
        transaction_id: UUID,
        provider: str,
        status: str,
        category: str,
        amount: Decimal,
        currency: str,
        external_id: str,
        payment_event_id: UUID | None = None,
        evidence_due_by: datetime | None = None,
        disputed_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentDisputeEntity:
        row = PaymentDispute.objects.create(
            transaction_id=transaction_id,
            provider=provider,
            status=status,
            category=category,
            amount=amount,
            currency=currency,
            external_id=external_id,
            payment_event_id=payment_event_id,
            evidence_due_by=evidence_due_by,
            disputed_at=disputed_at,
            metadata=metadata or {},
        )
        return dispute_orm_to_entity(row)

    def update_dispute_status(
        self,
        *,
        dispute_id: UUID,
        status: str,
        resolved_at: datetime | None = None,
    ) -> PaymentDisputeEntity:
        row = PaymentDispute.objects.get(id=dispute_id)
        row.status = status
        update_fields = ["status", "updated_at"]
        if resolved_at:
            row.resolved_at = resolved_at
            update_fields.append("resolved_at")
        row.save(update_fields=update_fields)
        return dispute_orm_to_entity(row)

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentDisputeEntity | None:
        row = PaymentDispute.objects.filter(provider=provider, external_id=external_id).first()
        return dispute_orm_to_entity(row) if row else None

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.domain.entities.payment_payout_entity import PaymentPayoutEntity
from components.payments.mappers.db.payment_payout_mapper import payout_orm_to_entity
from infrastructure.persistence.workspaces.payments.models import PaymentPayout


class OrmPaymentPayoutRepository:
    def create_payout(
        self,
        *,
        workspace_id: UUID,
        method_id: UUID,
        provider: str,
        amount: Decimal,
        currency: str,
        external_id: str,
        arrival_date: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentPayoutEntity:
        row = PaymentPayout.objects.create(
            workspace_id=workspace_id,
            method_id=method_id,
            provider=provider,
            amount=amount,
            currency=currency,
            external_id=external_id,
            arrival_date=arrival_date,
            metadata=metadata or {},
        )
        return payout_orm_to_entity(row)

    def update_payout_status(
        self,
        *,
        payout_id: UUID,
        status: str,
        failure_code: str = "",
        failure_message: str = "",
    ) -> PaymentPayoutEntity:
        row = PaymentPayout.objects.get(id=payout_id)
        row.status = status
        update_fields = ["status", "updated_at"]
        if failure_code:
            row.failure_code = failure_code
            update_fields.append("failure_code")
        if failure_message:
            row.failure_message = failure_message
            update_fields.append("failure_message")
        row.save(update_fields=update_fields)
        return payout_orm_to_entity(row)

    def find_by_external_id(self, *, provider: str, external_id: str) -> PaymentPayoutEntity | None:
        row = PaymentPayout.objects.filter(provider=provider, external_id=external_id).first()
        return payout_orm_to_entity(row) if row else None

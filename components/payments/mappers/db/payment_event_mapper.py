from __future__ import annotations

from components.payments.domain.entities.payment_event_entity import PaymentEventEntity
from infrastructure.persistence.workspaces.payments.models import PaymentEvent


def to_payment_event_entity(event: PaymentEvent) -> PaymentEventEntity:
    return PaymentEventEntity(
        id=event.id,
        provider=event.provider,
        provider_event_id=event.event_id,
        event_type=event.event_type,
        status=event.status,
        workspace_id=event.workspace_id,
        method_id=event.method_id,
        payload=event.payload or {},
    )

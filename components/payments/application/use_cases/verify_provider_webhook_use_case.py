from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.payments.application.use_cases.record_and_claim_payment_event_use_case import (
    RecordAndClaimPaymentEventResult,
    RecordAndClaimPaymentEventUseCase,
)


@dataclass(frozen=True)
class VerifiedProviderWebhookEnvelope:
    provider: str
    event: object
    account_id: str | None
    workspace_id: UUID | None
    method_id: UUID | None


@dataclass(frozen=True)
class VerifiedWebhookHandlingResult:
    intake: RecordAndClaimPaymentEventResult
    normalized_event: dict[str, Any] | None


class VerifyProviderWebhookUseCase:
    def __init__(self, payment_event_intake: RecordAndClaimPaymentEventUseCase):
        self.payment_event_intake = payment_event_intake

    def execute(
        self,
        *,
        envelope: VerifiedProviderWebhookEnvelope,
        claimed_by: str,
        claim_message: str | None = None,
    ) -> VerifiedWebhookHandlingResult:
        event = envelope.event
        event_id = None
        event_type = None
        external_id = None
        amount: Decimal | None = None
        currency = None
        normalized_event = event if isinstance(event, dict) else None

        if envelope.provider == "stripe":
            if hasattr(event, "id"):
                event_id = getattr(event, "id", None)
                event_type = getattr(event, "type", None)
                data = getattr(event, "data", None)
                data_object = data.get("object") if isinstance(data, dict) else None
                if isinstance(data_object, dict):
                    external_id = data_object.get("id")
                    amount = data_object.get("amount") or data_object.get("amount_total")
                    currency = data_object.get("currency")
            elif isinstance(event, dict):
                event_id = event.get("id")
                event_type = event.get("type")
                data_object = (event.get("data") or {}).get("object") if isinstance(event.get("data"), dict) else None
                if isinstance(data_object, dict):
                    external_id = data_object.get("id")
                    amount = data_object.get("amount") or data_object.get("amount_total")
                    currency = data_object.get("currency")
            if not isinstance(event, dict) and hasattr(event, "to_dict_recursive"):
                try:
                    normalized_event = event.to_dict_recursive()
                except Exception:
                    normalized_event = None
        elif envelope.provider == "braintree" and isinstance(event, dict):
            event_id = event.get("id")
            event_type = event.get("kind")
            transaction = event.get("transaction") or {}
            if isinstance(transaction, dict):
                external_id = transaction.get("id")
                amount = transaction.get("amount")
                currency = transaction.get("currency")
            subscription = event.get("subscription") or {}
            if isinstance(subscription, dict) and not external_id:
                external_id = subscription.get("id")
            normalized_event = event
        elif envelope.provider == "bitpay" and isinstance(event, dict):
            invoice = event.get("event", {}).get("data") or event.get("data") or event
            if isinstance(invoice, dict):
                event_id = invoice.get("id") or invoice.get("token")
                external_id = invoice.get("id")
                event_type = invoice.get("status") or event.get("type")
                amount = invoice.get("price")
                currency = invoice.get("currency")
            normalized_event = event

        intake = self.payment_event_intake.execute(
            provider=envelope.provider,
            provider_account_id=envelope.account_id,
            provider_event_id=event_id or "",
            external_id=external_id,
            event_type=event_type,
            workspace_id=envelope.workspace_id,
            method_id=envelope.method_id,
            amount=amount,
            currency=currency,
            payload=normalized_event,
            claimed_by=claimed_by,
            message=claim_message,
        )
        return VerifiedWebhookHandlingResult(intake=intake, normalized_event=normalized_event)

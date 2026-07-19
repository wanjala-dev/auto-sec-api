from __future__ import annotations

from typing import Any
from components.payments.infrastructure.services.stripe_invoice_helpers import (
    resolve_invoice_subscription_id,
)


def summarize_payment_method(
    payment_method: dict[str, Any],
    is_default: bool = False,
) -> dict[str, object]:
    """Format a payment method for API response."""
    card = payment_method.get("card") or {}
    return {
        "id": payment_method.get("id"),
        "brand": card.get("brand"),
        "last4": card.get("last4"),
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
        "is_default": is_default,
    }


def format_invoice_row(invoice: dict[str, Any]) -> dict[str, Any]:
    """Format an invoice for history/list response."""
    return {
        "id": invoice.get("id"),
        "number": invoice.get("number"),
        "status": invoice.get("status"),
        "amount_due": invoice.get("amount_due"),
        "amount_paid": invoice.get("amount_paid"),
        "amount_remaining": invoice.get("amount_remaining"),
        "currency": invoice.get("currency"),
        "created": invoice.get("created"),
        "period_start": invoice.get("period_start"),
        "period_end": invoice.get("period_end"),
        "subscription": resolve_invoice_subscription_id(invoice),
        "hosted_invoice_url": invoice.get("hosted_invoice_url"),
        "invoice_pdf": invoice.get("invoice_pdf"),
    }


def format_upcoming_invoice(upcoming_invoice: dict[str, Any] | None) -> dict[str, Any] | None:
    """Format an upcoming invoice for overview response."""
    if not upcoming_invoice:
        return None
    return {
        "amount_due": upcoming_invoice.get("amount_due"),
        "currency": upcoming_invoice.get("currency"),
        "next_payment_attempt": upcoming_invoice.get("next_payment_attempt"),
        "hosted_invoice_url": upcoming_invoice.get("hosted_invoice_url"),
    }

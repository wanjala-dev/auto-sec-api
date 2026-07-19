from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.currency is None or not str(self.currency).strip():
            raise ValueError("Money.currency is required.")
        object.__setattr__(self, "currency", str(self.currency).strip().lower())


@dataclass(frozen=True)
class ExternalReference:
    value: str

    def __post_init__(self) -> None:
        if not str(self.value).strip():
            raise ValueError("ExternalReference.value is required.")
        object.__setattr__(self, "value", str(self.value).strip())


@dataclass(frozen=True)
class ProviderEventId:
    value: str

    def __post_init__(self) -> None:
        if not str(self.value).strip():
            raise ValueError("ProviderEventId.value is required.")
        object.__setattr__(self, "value", str(self.value).strip())


@dataclass(frozen=True)
class PaymentEventType:
    value: str

    def __post_init__(self) -> None:
        if not str(self.value).strip():
            raise ValueError("PaymentEventType.value is required.")
        object.__setattr__(self, "value", str(self.value).strip())


@dataclass(frozen=True)
class PaymentOnboardingLink:
    account_id: str
    redirect_url: str
    expires_at: int | None = None
    created_account: bool = False


@dataclass(frozen=True)
class ConnectedPaymentAccount:
    account_id: str
    details_submitted: bool
    charges_enabled: bool
    payouts_enabled: bool
    capabilities: dict[str, Any]
    requirements: dict[str, Any]
    # ISO 4217 code the provider will settle payouts in. Captured at
    # connect/onboarding time so WorkspacePaymentMethod.settlement_currency
    # lands correct for every new row — no backfill needed.
    default_currency: str | None = None


@dataclass(frozen=True)
class DisputeCategory:
    value: str

    VALID = frozenset({
        "general",
        "fraudulent",
        "duplicate",
        "product_not_received",
        "product_unacceptable",
        "subscription_cancelled",
        "unrecognized",
        "credit_not_processed",
    })

    def __post_init__(self) -> None:
        if self.value not in self.VALID:
            raise ValueError(f"Invalid dispute category: {self.value}")


@dataclass(frozen=True)
class RefundReason:
    value: str

    VALID = frozenset({
        "requested_by_customer",
        "duplicate",
        "fraudulent",
        "other",
    })

    def __post_init__(self) -> None:
        if self.value not in self.VALID:
            raise ValueError(f"Invalid refund reason: {self.value}")

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from components.shared_kernel.application.commands import Command


@dataclass(frozen=True, kw_only=True)
class RecordPaymentEvent(Command):
    provider: str
    provider_event_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    workspace_id: UUID | None = None
    method_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class ClaimPaymentEvent(Command):
    payment_event_id: UUID
    claimed_by: str


@dataclass(frozen=True, kw_only=True)
class CreatePaymentOrder(Command):
    method_id: UUID
    context: str
    amount: Decimal | None = None
    currency: str = "usd"
    customer_email: str | None = None
    customer_name: str | None = None
    plan_id: UUID | None = None
    client_reference_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class VerifyProviderWebhook(Command):
    provider: str
    endpoint_name: str | None = None
    payload: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)

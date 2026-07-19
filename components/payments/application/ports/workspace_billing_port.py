from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class WorkspaceBillingContext:
    customer_id: str
    subscription_id: str | None


class WorkspaceBillingPort(Protocol):
    def get_context(self, *, workspace: Any) -> WorkspaceBillingContext: ...

    def fetch_customer(self, *, customer_id: str) -> dict[str, Any]: ...

    def fetch_subscription(self, *, subscription_id: str | None) -> dict[str, Any] | None: ...

    def list_payment_methods(self, *, customer_id: str) -> list[dict[str, Any]]: ...

    def list_invoices(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        limit: int,
        starting_after: str | None,
        ending_before: str | None,
    ) -> tuple[list[dict[str, Any]], bool]: ...

    def preview_upcoming_invoice(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
    ) -> dict[str, Any] | None: ...

    def create_setup_intent(self, *, customer_id: str) -> dict[str, Any]: ...

    def retrieve_payment_method(self, *, payment_method_id: str) -> dict[str, Any]: ...

    def set_default_payment_method(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        subscription_id: str | None,
    ) -> None: ...

    def detach_payment_method(self, *, payment_method_id: str) -> None: ...

    def resolve_default_payment_method_id(
        self,
        *,
        subscription: dict[str, Any] | None,
        customer: dict[str, Any] | None,
    ) -> str | None: ...

    def get_publishable_key(self) -> str | None: ...

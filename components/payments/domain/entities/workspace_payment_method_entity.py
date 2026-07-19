from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from components.payments.domain.errors import UnsupportedPaymentProviderError
from components.payments.domain.value_objects import ConnectedPaymentAccount


@dataclass
class WorkspacePaymentMethodEntity:
    id: UUID
    workspace_id: UUID
    provider_slug: str
    status: str
    is_primary: bool
    provider_account_id: str = ""
    settlement_currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    credentials: dict[str, Any] = field(default_factory=dict)
    last_error: str = ""
    owner_email: str | None = None
    display_name: str | None = None
    workspace_name: str | None = None

    STATUS_ACTIVE = "active"
    STATUS_PENDING = "pending"
    STATUS_REQUIRES_ACTION = "requires_action"
    STATUS_DISABLED = "disabled"
    STRIPE_PROVIDER = "stripe"

    def __post_init__(self) -> None:
        if not self.provider_slug:
            raise ValueError("WorkspacePaymentMethodEntity.provider_slug is required.")
        if not self.status:
            raise ValueError("WorkspacePaymentMethodEntity.status is required.")

    def require_stripe_provider(self) -> None:
        if self.provider_slug != self.STRIPE_PROVIDER:
            raise UnsupportedPaymentProviderError("Only Stripe Connect authorization is implemented.")

    def mark_as_primary(self) -> None:
        self.is_primary = True

    def onboarding_redirect(self, default: str) -> str:
        return str(self.metadata.get("post_onboard_redirect") or default or "")

    def onboarding_refresh_redirect(self, default: str) -> str:
        return str(self.metadata.get("post_onboard_refresh") or default or "")

    def expected_onboarding_state(self) -> str:
        return str(self.metadata.get("stripe_connect_state") or "")

    def begin_stripe_onboarding(
        self,
        *,
        state: str,
        redirect_url: str,
        refresh_url: str,
        account_id: str,
        expires_at: int | None,
        created_account: bool,
    ) -> None:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "stripe_connect_state": state,
                "post_onboard_redirect": redirect_url,
                "post_onboard_refresh": refresh_url,
                "stripe_account_id": account_id,
                "stripe_authorize_expires_at": expires_at,
            }
        )
        credentials = dict(self.credentials)
        credentials["account_id"] = account_id

        self.metadata = metadata
        self.credentials = credentials
        self.provider_account_id = account_id
        self.last_error = ""
        if created_account:
            self.status = self.STATUS_PENDING

    def mark_onboarding_failed(self, message: str) -> None:
        self.last_error = message
        self.status = self.STATUS_REQUIRES_ACTION

    def complete_stripe_onboarding(self, account: ConnectedPaymentAccount) -> None:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "stripe_account_id": account.account_id,
                "stripe_details_submitted": account.details_submitted,
                "stripe_charges_enabled": account.charges_enabled,
                "stripe_payouts_enabled": account.payouts_enabled,
                "stripe_capabilities": account.capabilities,
                "stripe_requirements": account.requirements,
                "stripe_onboarded_at": datetime.now(UTC).isoformat(),
            }
        )
        metadata.pop("stripe_connect_state", None)

        credentials = dict(self.credentials)
        credentials["account_id"] = account.account_id

        self.metadata = metadata
        self.credentials = credentials
        self.provider_account_id = account.account_id
        # Stripe returns default_currency lowercase — we normalize to
        # uppercase upstream in the gateway, but keep this defensive
        # in case another adapter forgets.
        if account.default_currency:
            self.settlement_currency = account.default_currency.upper()
        self.last_error = ""
        self.status = (
            self.STATUS_ACTIVE if account.charges_enabled else self.STATUS_REQUIRES_ACTION
        )

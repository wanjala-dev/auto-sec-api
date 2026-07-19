from __future__ import annotations

from typing import Protocol

from components.payments.domain.value_objects import (
    ConnectedPaymentAccount,
    PaymentOnboardingLink,
)


class PaymentOnboardingPort(Protocol):
    def start_workspace_onboarding(
        self,
        *,
        existing_account_id: str | None,
        owner_email: str | None,
        return_url: str,
        refresh_url: str,
        display_name: str | None = None,
        workspace_id: str | None = None,
        method_id: str | None = None,
    ) -> PaymentOnboardingLink: ...

    def fetch_connected_account(self, *, account_id: str) -> ConnectedPaymentAccount: ...

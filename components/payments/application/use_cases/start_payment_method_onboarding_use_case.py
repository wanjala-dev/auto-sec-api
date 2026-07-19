from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.payments.domain.errors import (
    PaymentMethodNotFoundError,
    PaymentOnboardingError,
)
from components.payments.application.ports.payment_method_management_port import (
    PaymentMethodManagementPort,
)
from components.payments.application.ports.payment_onboarding_port import PaymentOnboardingPort


@dataclass(frozen=True)
class StartPaymentMethodOnboardingResult:
    redirect_url: str
    state: str
    account_id: str
    expires_at: int | None


class StartPaymentMethodOnboardingUseCase:
    """Start workspace payment-method onboarding."""

    def __init__(
        self,
        payment_methods: PaymentMethodManagementPort,
        onboarding: PaymentOnboardingPort,
    ):
        self.payment_methods = payment_methods
        self.onboarding = onboarding

    def execute(
        self,
        *,
        method_id: UUID,
        state: str,
        post_onboard_redirect: str,
        post_onboard_refresh: str,
        callback_success_url: str,
        callback_refresh_url: str,
        updated_by_id: UUID | None = None,
    ) -> StartPaymentMethodOnboardingResult:
        method = self.payment_methods.get_method(method_id=method_id)
        if method is None:
            raise PaymentMethodNotFoundError("Payment method was not found.")

        method.require_stripe_provider()

        # Build a human-readable display name so each Connect account is
        # distinguishable in the Stripe Dashboard. Without this every
        # account on the platform shows up as the owner email and ops
        # can't tell them apart. Format: "<workspace> · <method>" or just
        # one of them when the other is missing.
        display_name_parts = [
            part
            for part in (method.workspace_name, method.display_name)
            if part
        ]
        display_name = " · ".join(display_name_parts) if display_name_parts else None

        try:
            onboarding_link = self.onboarding.start_workspace_onboarding(
                existing_account_id=method.provider_account_id or method.metadata.get("stripe_account_id"),
                owner_email=method.owner_email,
                return_url=callback_success_url,
                refresh_url=callback_refresh_url,
                display_name=display_name,
                workspace_id=str(method.workspace_id) if method.workspace_id else None,
                method_id=str(method.id) if method.id else None,
            )
        except PaymentOnboardingError as exc:
            method.mark_onboarding_failed(exc.details)
            self.payment_methods.save_method(method=method, updated_by_id=updated_by_id)
            raise

        method.begin_stripe_onboarding(
            state=state,
            redirect_url=post_onboard_redirect,
            refresh_url=post_onboard_refresh,
            account_id=onboarding_link.account_id,
            expires_at=onboarding_link.expires_at,
            created_account=onboarding_link.created_account,
        )
        self.payment_methods.save_method(method=method, updated_by_id=updated_by_id)

        return StartPaymentMethodOnboardingResult(
            redirect_url=onboarding_link.redirect_url,
            state=state,
            account_id=onboarding_link.account_id,
            expires_at=onboarding_link.expires_at,
        )

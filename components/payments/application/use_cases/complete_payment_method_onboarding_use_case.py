from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.payments.domain.errors import (
    PaymentMethodNotFoundError,
    PaymentOnboardingConfigurationError,
    PaymentOnboardingError,
)
from components.payments.application.ports.payment_method_management_port import (
    PaymentMethodManagementPort,
)
from components.payments.application.ports.payment_onboarding_port import PaymentOnboardingPort
from components.payments.application.ports.payment_plan_sync_port import PaymentPlanSyncPort
from components.money.application.reconcile_workspace_currency_service import (
    ReconcileWorkspaceCurrency,
)


@dataclass(frozen=True)
class CompletePaymentMethodOnboardingResult:
    redirect_target: str
    status_code: str
    extra_params: dict[str, Any] = field(default_factory=dict)


class CompletePaymentMethodOnboardingUseCase:
    """Finalize workspace payment-method onboarding."""

    def __init__(
        self,
        payment_methods: PaymentMethodManagementPort,
        onboarding: PaymentOnboardingPort,
        plan_sync: PaymentPlanSyncPort,
        currency_reconciler: ReconcileWorkspaceCurrency | None = None,
    ):
        self.payment_methods = payment_methods
        self.onboarding = onboarding
        self.plan_sync = plan_sync
        # Keeps Workspace.default_currency in sync with the connected account's
        # settlement currency the moment onboarding completes (single source of
        # truth — see docs/plans/CURRENCY_SINGLE_SOURCE_OF_TRUTH.md P0c).
        self.currency_reconciler = currency_reconciler

    def execute(
        self,
        *,
        method_id: UUID,
        state: str | None,
        result: str,
        error_code: str | None,
        error_description: str | None,
        account_hint: str | None,
    ) -> CompletePaymentMethodOnboardingResult:
        method = self.payment_methods.get_method(method_id=method_id)
        if method is None:
            raise PaymentMethodNotFoundError("Payment method was not found.")

        redirect_success = method.onboarding_redirect(default="")
        redirect_refresh = method.onboarding_refresh_redirect(default=redirect_success)

        if result == "refresh":
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_refresh,
                status_code="refresh",
            )

        expected_state = method.expected_onboarding_state()
        if not state or state != expected_state:
            method.mark_onboarding_failed("Stripe onboarding state mismatch.")
            self.payment_methods.save_method(method=method)
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_success,
                status_code="state_mismatch",
            )

        if error_code:
            combined_error = error_code
            if error_description:
                combined_error = f"{error_code}: {error_description}"
            method.mark_onboarding_failed(combined_error)
            self.payment_methods.save_method(method=method)
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_success,
                status_code="error",
                extra_params={"reason": error_code},
            )

        account_id = account_hint or method.provider_account_id or method.metadata.get("stripe_account_id")
        if not account_id:
            method.mark_onboarding_failed("Missing Stripe account information after onboarding.")
            self.payment_methods.save_method(method=method)
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_success,
                status_code="missing_account",
            )

        try:
            account = self.onboarding.fetch_connected_account(account_id=account_id)
        except PaymentOnboardingConfigurationError as exc:
            method.mark_onboarding_failed(str(exc))
            self.payment_methods.save_method(method=method)
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_success,
                status_code="server_error",
            )
        except PaymentOnboardingError as exc:
            method.mark_onboarding_failed(exc.details)
            self.payment_methods.save_method(method=method)
            return CompletePaymentMethodOnboardingResult(
                redirect_target=redirect_success,
                status_code="stripe_error",
            )

        method.complete_stripe_onboarding(account)
        self.payment_methods.save_method(method=method)

        # Reconcile the workspace's display currency to the account it just
        # connected, so goals/dashboards stop showing a stale USD default when
        # the account settles in, say, CAD. No-op if no reconciler is wired.
        if self.currency_reconciler is not None and method.settlement_currency:
            self.currency_reconciler.execute(workspace_id=str(method.workspace_id))

        try:
            self.plan_sync.sync_method_plans(method_id=method.id)
        except Exception as exc:
            method.mark_onboarding_failed(f"Plan sync failed: {exc}")
            self.payment_methods.save_method(method=method)

        return CompletePaymentMethodOnboardingResult(
            redirect_target=redirect_success,
            status_code=(
                "success"
                if method.status == method.STATUS_ACTIVE
                else "needs_attention"
            ),
        )

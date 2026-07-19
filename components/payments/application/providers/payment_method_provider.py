from __future__ import annotations

from components.payments.application.providers.payment_gateway_provider import (
    make_payment_gateway_provider,
)
from components.payments.application.service import PaymentMethodService
from components.payments.application.use_cases.complete_payment_method_onboarding_use_case import (
    CompletePaymentMethodOnboardingUseCase,
)
from components.payments.application.use_cases.delete_payment_method_use_case import (
    DeletePaymentMethodUseCase,
)
from components.payments.application.use_cases.set_primary_payment_method_use_case import (
    SetPrimaryPaymentMethodUseCase,
)
from components.payments.application.use_cases.start_payment_method_onboarding_use_case import (
    StartPaymentMethodOnboardingUseCase,
)
from components.payments.infrastructure.adapters.payment_method_credentials_adapter import (
    PaymentMethodCredentialsAdapter,
)
from components.payments.infrastructure.gateways.payment_plan_sync_gateway import (
    PaymentPlanSyncGateway,
)
from components.payments.infrastructure.gateways.stripe_connect_onboarding_gateway import (
    StripeConnectOnboardingGateway,
)
from components.payments.infrastructure.repositories.payment_method_management_repository import (
    PaymentMethodManagementRepository,
)
from components.money.application.providers.reconcile_workspace_currency_provider import (
    get_reconcile_workspace_currency_provider,
)


class PaymentMethodProvider:
    def build_service(self) -> PaymentMethodService:
        return PaymentMethodService(
            credentials_port=PaymentMethodCredentialsAdapter(),
        )

    def build_set_primary_use_case(self) -> SetPrimaryPaymentMethodUseCase:
        return SetPrimaryPaymentMethodUseCase(PaymentMethodManagementRepository())

    def build_delete_use_case(self) -> DeletePaymentMethodUseCase:
        return DeletePaymentMethodUseCase(PaymentMethodManagementRepository())

    def build_start_onboarding_use_case(self) -> StartPaymentMethodOnboardingUseCase:
        return StartPaymentMethodOnboardingUseCase(
            payment_methods=PaymentMethodManagementRepository(),
            onboarding=StripeConnectOnboardingGateway(),
        )

    def build_complete_onboarding_use_case(self) -> CompletePaymentMethodOnboardingUseCase:
        return CompletePaymentMethodOnboardingUseCase(
            payment_methods=PaymentMethodManagementRepository(),
            onboarding=StripeConnectOnboardingGateway(),
            plan_sync=PaymentPlanSyncGateway(
                gateway_provider=make_payment_gateway_provider(),
            ),
            currency_reconciler=get_reconcile_workspace_currency_provider().build(),
        )

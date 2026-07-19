from __future__ import annotations

from components.payments.application.use_cases.cancel_payment_flow_use_case import (
    CancelPaymentFlowUseCase,
)
from components.payments.application.use_cases.finalize_failed_payment_use_case import (
    FinalizeFailedPaymentUseCase,
)
from components.payments.application.use_cases.finalize_successful_payment_use_case import (
    FinalizeSuccessfulPaymentUseCase,
)
from components.payments.application.use_cases.mark_payment_flow_processing_use_case import (
    MarkPaymentFlowProcessingUseCase,
)
from components.payments.application.use_cases.mark_payment_flow_requires_action_use_case import (
    MarkPaymentFlowRequiresActionUseCase,
)
from components.payments.infrastructure.repositories.orm_payment_flow_state_repository import (
    OrmPaymentFlowStateRepository,
)


class PaymentFlowStateProvider:
    def build_finalize_successful_use_case(self) -> FinalizeSuccessfulPaymentUseCase:
        return FinalizeSuccessfulPaymentUseCase(OrmPaymentFlowStateRepository())

    def build_mark_processing_use_case(self) -> MarkPaymentFlowProcessingUseCase:
        return MarkPaymentFlowProcessingUseCase(OrmPaymentFlowStateRepository())

    def build_finalize_failed_use_case(self) -> FinalizeFailedPaymentUseCase:
        return FinalizeFailedPaymentUseCase(OrmPaymentFlowStateRepository())

    def build_requires_action_use_case(self) -> MarkPaymentFlowRequiresActionUseCase:
        return MarkPaymentFlowRequiresActionUseCase(OrmPaymentFlowStateRepository())

    def build_cancel_use_case(self) -> CancelPaymentFlowUseCase:
        return CancelPaymentFlowUseCase(OrmPaymentFlowStateRepository())

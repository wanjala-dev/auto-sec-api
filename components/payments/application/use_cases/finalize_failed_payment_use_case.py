from __future__ import annotations

from components.payments.application.ports.payment_flow_state_port import PaymentFlowStatePort


class FinalizeFailedPaymentUseCase:
    def __init__(self, payment_flow_state: PaymentFlowStatePort):
        self.payment_flow_state = payment_flow_state

    def execute(
        self,
        *,
        order,
        attempt,
        message: str,
    ) -> None:
        self.payment_flow_state.mark_failed(
            order=order,
            attempt=attempt,
            message=message,
        )

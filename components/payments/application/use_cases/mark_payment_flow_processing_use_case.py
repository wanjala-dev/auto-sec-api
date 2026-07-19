from __future__ import annotations

from components.payments.application.ports.payment_flow_state_port import PaymentFlowStatePort


class MarkPaymentFlowProcessingUseCase:
    def __init__(self, payment_flow_state: PaymentFlowStatePort):
        self.payment_flow_state = payment_flow_state

    def execute(
        self,
        *,
        order,
        attempt,
        gateway_reference: str,
        gateway_reference_type: str,
    ) -> None:
        self.payment_flow_state.mark_processing(
            order=order,
            attempt=attempt,
            gateway_reference=gateway_reference,
            gateway_reference_type=gateway_reference_type,
        )

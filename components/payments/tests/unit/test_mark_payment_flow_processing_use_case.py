from __future__ import annotations

from components.payments.application.use_cases.mark_payment_flow_processing_use_case import (
    MarkPaymentFlowProcessingUseCase,
)


class _FakePaymentFlowState:
    def __init__(self):
        self.calls = []

    def mark_succeeded(self, **kwargs):
        self.calls.append(("succeeded", kwargs))

    def mark_processing(self, **kwargs):
        self.calls.append(("processing", kwargs))


def test_mark_payment_flow_processing_use_case_delegates_to_state_port():
    state = _FakePaymentFlowState()

    MarkPaymentFlowProcessingUseCase(state).execute(
        order="order-1",
        attempt="attempt-1",
        gateway_reference="sub_123",
        gateway_reference_type="subscription",
    )

    assert state.calls == [
        (
            "processing",
            {
                "order": "order-1",
                "attempt": "attempt-1",
                "gateway_reference": "sub_123",
                "gateway_reference_type": "subscription",
            },
        )
    ]

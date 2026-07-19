from __future__ import annotations

from components.payments.application.use_cases.cancel_payment_flow_use_case import (
    CancelPaymentFlowUseCase,
)


class _FakePaymentFlowState:
    def __init__(self):
        self.calls = []

    def mark_canceled(self, **kwargs):
        self.calls.append(("canceled", kwargs))


def test_cancel_payment_flow_use_case_delegates_to_state_port():
    state = _FakePaymentFlowState()

    CancelPaymentFlowUseCase(state).execute(
        order="order-1",
        attempt="attempt-1",
        message="session expired",
    )

    assert state.calls == [
        (
            "canceled",
            {
                "order": "order-1",
                "attempt": "attempt-1",
                "message": "session expired",
            },
        )
    ]

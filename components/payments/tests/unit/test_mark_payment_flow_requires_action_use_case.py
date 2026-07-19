from __future__ import annotations

from components.payments.application.use_cases.mark_payment_flow_requires_action_use_case import (
    MarkPaymentFlowRequiresActionUseCase,
)


class _FakePaymentFlowState:
    def __init__(self):
        self.calls = []

    def mark_requires_action(self, **kwargs):
        self.calls.append(("requires_action", kwargs))


def test_mark_payment_flow_requires_action_use_case_delegates_to_state_port():
    state = _FakePaymentFlowState()

    MarkPaymentFlowRequiresActionUseCase(state).execute(
        order="order-1",
        attempt="attempt-1",
        message="payment failed",
    )

    assert state.calls == [
        (
            "requires_action",
            {
                "order": "order-1",
                "attempt": "attempt-1",
                "message": "payment failed",
            },
        )
    ]

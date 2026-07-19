from __future__ import annotations

from components.payments.application.use_cases.finalize_successful_payment_use_case import (
    FinalizeSuccessfulPaymentUseCase,
)


class _FakePaymentFlowState:
    def __init__(self):
        self.calls = []

    def mark_succeeded(self, **kwargs):
        self.calls.append(("succeeded", kwargs))


def test_finalize_successful_payment_use_case_delegates_to_state_port():
    state = _FakePaymentFlowState()

    FinalizeSuccessfulPaymentUseCase(state).execute(
        order="order-1",
        attempt="attempt-1",
    )

    assert state.calls == [
        (
            "succeeded",
            {
                "order": "order-1",
                "attempt": "attempt-1",
            },
        )
    ]

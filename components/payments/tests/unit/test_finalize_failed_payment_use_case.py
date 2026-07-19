from __future__ import annotations

from components.payments.application.use_cases.finalize_failed_payment_use_case import (
    FinalizeFailedPaymentUseCase,
)


class _FakePaymentFlowState:
    def __init__(self):
        self.calls = []

    def mark_failed(self, **kwargs):
        self.calls.append(("failed", kwargs))


def test_finalize_failed_payment_use_case_delegates_to_state_port():
    state = _FakePaymentFlowState()

    FinalizeFailedPaymentUseCase(state).execute(
        order="order-1",
        attempt="attempt-1",
        message="gateway failed",
    )

    assert state.calls == [
        (
            "failed",
            {
                "order": "order-1",
                "attempt": "attempt-1",
                "message": "gateway failed",
            },
        )
    ]

from __future__ import annotations

from uuid import UUID

from components.payments.domain.errors import PaymentMethodNotFoundError
from components.payments.application.ports.payment_method_management_port import (
    PaymentMethodManagementPort,
)


class SetPrimaryPaymentMethodUseCase:
    """Promote one payment method as the provider-primary method."""

    def __init__(self, payment_methods: PaymentMethodManagementPort):
        self.payment_methods = payment_methods

    def execute(self, *, method_id: UUID, updated_by_id: UUID | None = None):
        method = self.payment_methods.set_primary_method(
            method_id=method_id,
            updated_by_id=updated_by_id,
        )
        if method is None:
            raise PaymentMethodNotFoundError("Payment method was not found.")
        return method

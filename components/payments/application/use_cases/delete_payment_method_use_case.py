from __future__ import annotations

from uuid import UUID

from components.payments.domain.errors import PaymentMethodNotFoundError
from components.payments.application.ports.payment_method_management_port import (
    PaymentMethodManagementPort,
)


class DeletePaymentMethodUseCase:
    def __init__(self, payment_methods: PaymentMethodManagementPort):
        self.payment_methods = payment_methods

    def execute(
        self,
        *,
        method_id: UUID,
        updated_by_id: UUID | None = None,
    ) -> None:
        deleted = self.payment_methods.soft_delete_method(
            method_id=method_id,
            updated_by_id=updated_by_id,
        )
        if not deleted:
            raise PaymentMethodNotFoundError(
                f"Payment method '{method_id}' was not found."
            )

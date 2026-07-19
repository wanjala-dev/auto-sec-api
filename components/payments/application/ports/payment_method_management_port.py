from __future__ import annotations

from typing import Protocol
from uuid import UUID

from components.payments.domain.entities.workspace_payment_method_entity import (
    WorkspacePaymentMethodEntity,
)


class PaymentMethodManagementPort(Protocol):
    def get_method(self, *, method_id: UUID) -> WorkspacePaymentMethodEntity | None: ...

    def save_method(
        self,
        *,
        method: WorkspacePaymentMethodEntity,
        updated_by_id: UUID | None = None,
    ) -> None: ...

    def set_primary_method(
        self,
        *,
        method_id: UUID,
        updated_by_id: UUID | None = None,
    ) -> WorkspacePaymentMethodEntity | None: ...

    def soft_delete_method(
        self,
        *,
        method_id: UUID,
        updated_by_id: UUID | None = None,
    ) -> bool: ...

from __future__ import annotations

from components.payments.infrastructure.adapters.payment_utils import resolve_workspace_payment_method
from components.payments.application.ports.payment_method_selection_port import (
    PaymentMethodSelectionPort,
)
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


class OrmPaymentMethodSelectionRepository(PaymentMethodSelectionPort):
    """Resolve checkout payment methods from the legacy ORM models."""

    def resolve_method(
        self,
        *,
        workspace: Workspace,
        context: str,
        payment_method_id: str | None = None,
    ) -> WorkspacePaymentMethod | None:
        method = None
        if payment_method_id:
            method = (
                WorkspacePaymentMethod.objects.filter(
                    id=payment_method_id,
                    workspace=workspace,
                    status=WorkspacePaymentMethod.STATUS_ACTIVE,
                    is_deleted=False,
                )
                .select_related("provider")
                .first()
            )
        if not method:
            method = resolve_workspace_payment_method(workspace, context=context)
        return method

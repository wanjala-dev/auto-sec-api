from __future__ import annotations

from components.payments.domain.entities.workspace_payment_method_entity import (
    WorkspacePaymentMethodEntity,
)
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
)
from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


def to_workspace_payment_method_entity(
    method: WorkspacePaymentMethod,
) -> WorkspacePaymentMethodEntity:
    workspace = getattr(method, "workspace", None)
    owner = getattr(workspace, "workspace_owner", None)
    owner_email = getattr(owner, "email", None)
    workspace_name = getattr(workspace, "workspace_name", None) or getattr(
        workspace, "name", None
    )
    return WorkspacePaymentMethodEntity(
        id=method.id,
        workspace_id=method.workspace_id,
        provider_slug=method.provider.slug,
        status=method.status,
        is_primary=method.is_primary,
        provider_account_id=method.provider_account_id or "",
        settlement_currency=method.settlement_currency or None,
        metadata=dict(method.metadata or {}),
        credentials=read_payment_method_credentials(method),
        last_error=method.last_error or "",
        owner_email=owner_email,
        display_name=method.display_name,
        workspace_name=workspace_name,
    )

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from components.payments.infrastructure.adapters.payment_method_credentials import (
    write_payment_method_credentials,
)
from components.payments.mappers.db.workspace_payment_method_mapper import (
    to_workspace_payment_method_entity,
)
from components.payments.application.ports.payment_method_management_port import (
    PaymentMethodManagementPort,
)
from infrastructure.persistence.workspaces.payments.models import PaymentWebhookEndpoint, WorkspacePaymentMethod


class PaymentMethodManagementRepository(PaymentMethodManagementPort):
    """Transitional repository for payment-method administration workflows."""

    def get_method(self, *, method_id: UUID):
        method = (
            WorkspacePaymentMethod.objects.filter(id=method_id, is_deleted=False)
            .select_related("provider", "workspace__workspace_owner")
            .first()
        )
        if not method:
            return None
        return to_workspace_payment_method_entity(method)

    def save_method(
        self,
        *,
        method,
        updated_by_id: UUID | None = None,
    ) -> None:
        orm_method = WorkspacePaymentMethod.objects.get(id=method.id, is_deleted=False)
        orm_method.provider_account_id = method.provider_account_id
        orm_method.settlement_currency = method.settlement_currency
        orm_method.metadata = dict(method.metadata)
        orm_method.last_error = method.last_error
        orm_method.status = method.status
        orm_method.is_primary = method.is_primary
        write_payment_method_credentials(orm_method, method.credentials)

        update_fields = [
            "provider_account_id",
            "settlement_currency",
            "metadata",
            "last_error",
            "status",
            "is_primary",
            "encrypted_credentials",
            "credentials_updated_at",
            "updated_at",
        ]
        if updated_by_id:
            orm_method.updated_by_id = updated_by_id
            update_fields.append("updated_by")
        orm_method.save(update_fields=update_fields)

    def set_primary_method(
        self,
        *,
        method_id: UUID,
        updated_by_id: UUID | None = None,
    ):
        method = (
            WorkspacePaymentMethod.objects.filter(id=method_id, is_deleted=False)
            .select_related("provider", "workspace__workspace_owner")
            .first()
        )
        if not method:
            return None

        WorkspacePaymentMethod.objects.filter(
            workspace=method.workspace,
            provider=method.provider,
            is_primary=True,
            is_deleted=False,
        ).exclude(id=method.id).update(is_primary=False)

        method.is_primary = True
        if updated_by_id:
            method.updated_by_id = updated_by_id
            method.save(update_fields=["is_primary", "updated_by", "updated_at"])
        else:
            method.save(update_fields=["is_primary", "updated_at"])

        return to_workspace_payment_method_entity(method)

    def soft_delete_method(
        self,
        *,
        method_id: UUID,
        updated_by_id: UUID | None = None,
    ) -> bool:
        method = (
            WorkspacePaymentMethod.objects.filter(id=method_id, is_deleted=False)
            .select_related("provider")
            .first()
        )
        if not method:
            return False

        now = timezone.now()
        with transaction.atomic():
            method.is_deleted = True
            method.deleted_at = now
            method.is_primary = False
            method.status = WorkspacePaymentMethod.STATUS_DISABLED
            update_fields = ["is_deleted", "deleted_at", "is_primary", "status", "updated_at"]
            if updated_by_id:
                method.updated_by_id = updated_by_id
                update_fields.append("updated_by")
            method.save(update_fields=update_fields)

            method.plans.filter(is_active=True).update(is_active=False, updated_at=now)
            method.webhooks.filter(status=PaymentWebhookEndpoint.STATUS_ACTIVE).update(
                status=PaymentWebhookEndpoint.STATUS_DISABLED,
                updated_at=now,
            )

        return True

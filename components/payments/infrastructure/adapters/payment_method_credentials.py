from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone

from components.payments.infrastructure.adapters.encryption import decrypt_json, encrypt_json

if TYPE_CHECKING:
    from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


def read_payment_method_credentials(method: WorkspacePaymentMethod) -> dict[str, Any]:
    return decrypt_json(method.encrypted_credentials)


def write_payment_method_credentials(
    method: WorkspacePaymentMethod,
    payload: dict[str, Any] | None,
) -> None:
    method.encrypted_credentials = encrypt_json(payload or {})
    method.credentials_updated_at = timezone.now()


def payment_method_has_credentials(method: WorkspacePaymentMethod) -> bool:
    return bool(read_payment_method_credentials(method))

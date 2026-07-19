from __future__ import annotations

from typing import TYPE_CHECKING, Any

from components.payments.infrastructure.adapters.payment_method_credentials import (
    write_payment_method_credentials,
)
from components.payments.application.ports.payment_method_credentials_port import (
    PaymentMethodCredentialsPort,
)

if TYPE_CHECKING:
    pass


class PaymentMethodCredentialsAdapter(PaymentMethodCredentialsPort):
    """Adapter that manages payment method credentials using ORM and encryption.

    Encapsulates all ORM-related queries and credential encryption logic,
    keeping this infrastructure code out of the application service.
    """

    def get_method(self, method_id: Any) -> Any:
        """Retrieve a payment method by ID.

        Filters for non-deleted methods and eagerly loads the provider relationship.

        Args:
            method_id: The ID of the payment method to retrieve

        Returns:
            The payment method entity

        Raises:
            ValueError: If the method is not found or is deleted
        """
        from infrastructure.persistence.workspaces.payments.models import (
            WorkspacePaymentMethod,
        )

        method = (
            WorkspacePaymentMethod.objects.filter(id=method_id, is_deleted=False)
            .select_related("provider")
            .first()
        )
        if not method:
            raise ValueError(f"Payment method {method_id} not found.")
        return method

    def write_credentials(self, method: Any, credentials: dict[str, Any]) -> None:
        """Encrypt and write credentials to a payment method.

        This method modifies the payment method's encrypted_credentials field
        and updates the credentials_updated_at timestamp, but does NOT save
        the changes to the database.

        Args:
            method: The payment method entity to update
            credentials: The plaintext credentials dict to encrypt
        """
        write_payment_method_credentials(method, credentials)

    def save_method(self, method: Any, updated_by_id: Any | None = None) -> None:
        """Persist payment method changes to the database.

        Saves the payment method with encrypted credentials and timestamp updates,
        optionally recording which user made the update.

        Args:
            method: The payment method entity to save
            updated_by_id: Optional user ID who performed the update
        """
        update_fields = ["encrypted_credentials", "credentials_updated_at", "updated_at"]
        if updated_by_id:
            method.updated_by_id = updated_by_id
            update_fields.append("updated_by")
        method.save(update_fields=update_fields)

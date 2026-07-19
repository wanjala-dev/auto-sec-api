from __future__ import annotations

from typing import Any, Protocol


class PaymentMethodCredentialsPort(Protocol):
    """Port for managing payment method credentials encryption and persistence.

    Abstracts the ORM interactions and credential handling logic away from
    the application service, keeping it focused on business logic.
    """

    def get_method(self, method_id: Any) -> Any:
        """Retrieve a payment method by ID.

        Args:
            method_id: The ID of the payment method to retrieve

        Returns:
            The payment method entity

        Raises:
            ValueError: If the method is not found or is deleted
        """
        ...

    def write_credentials(self, method: Any, credentials: dict[str, Any]) -> None:
        """Encrypt and write credentials to a payment method.

        This method modifies the payment method's encrypted_credentials field
        and updates the credentials_updated_at timestamp, but does NOT save
        the changes to the database.

        Args:
            method: The payment method entity to update
            credentials: The plaintext credentials dict to encrypt
        """
        ...

    def save_method(self, method: Any, updated_by_id: Any | None = None) -> None:
        """Persist payment method changes to the database.

        Saves the payment method with encrypted credentials and timestamp updates,
        optionally recording which user made the update.

        Args:
            method: The payment method entity to save
            updated_by_id: Optional user ID who performed the update
        """
        ...

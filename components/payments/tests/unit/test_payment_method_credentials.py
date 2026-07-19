from __future__ import annotations

from components.payments.infrastructure.adapters.payment_method_credentials import (
    payment_method_has_credentials,
    read_payment_method_credentials,
    write_payment_method_credentials,
)
from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


def test_payment_method_credentials_round_trip_without_model_helpers():
    method = WorkspacePaymentMethod(encrypted_credentials="")

    assert payment_method_has_credentials(method) is False

    write_payment_method_credentials(
        method,
        {"secret_key": "sk_test_123", "publishable_key": "pk_test_123"},
    )

    assert method.credentials_updated_at is not None
    assert payment_method_has_credentials(method) is True
    assert read_payment_method_credentials(method)["secret_key"] == "sk_test_123"

"""Provider/composition root for the payment-method credential helpers.

Controllers (``components/payments/api/controller.py``) consume
:class:`PaymentMethodCredentialsProvider` instead of importing the
concrete adapter directly. Keeps the API layer's import graph free of
infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter functions so module load is cheap
and tests can monkeypatch
``provider.read_payment_method_credentials`` /
``provider.write_payment_method_credentials`` without dragging in
``django.utils.timezone`` or the ORM model at test discovery time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from infrastructure.persistence.workspaces.payments.models import (
        WorkspacePaymentMethod,
    )


class PaymentMethodCredentialsProvider:
    """Driving-side façade for the payment-method credential adapter."""

    def read_payment_method_credentials(
        self, method: "WorkspacePaymentMethod"
    ) -> dict[str, Any]:
        from components.payments.infrastructure.adapters.payment_method_credentials import (
            read_payment_method_credentials as _read,
        )

        return _read(method)

    def write_payment_method_credentials(
        self,
        method: "WorkspacePaymentMethod",
        payload: dict[str, Any] | None,
    ) -> None:
        from components.payments.infrastructure.adapters.payment_method_credentials import (
            write_payment_method_credentials as _write,
        )

        return _write(method, payload)

    def payment_method_has_credentials(
        self, method: "WorkspacePaymentMethod"
    ) -> bool:
        from components.payments.infrastructure.adapters.payment_method_credentials import (
            payment_method_has_credentials as _has,
        )

        return _has(method)


_default = PaymentMethodCredentialsProvider()


def get_payment_method_credentials_provider() -> PaymentMethodCredentialsProvider:
    """Return the default provider — composition root for the payment-method
    credential adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default

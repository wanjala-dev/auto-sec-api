"""Provider/composition root for the payments encryption helpers.

Controllers (``components/payments/api/controller.py``) consume
:class:`PaymentEncryptionProvider` instead of importing the concrete
Fernet-backed adapter directly. Keeps the API layer's import graph free
of infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter symbols so module load is cheap
and tests can monkeypatch ``provider.encrypt_json`` /
``provider.decrypt_json`` without dragging in ``cryptography.fernet``
at test discovery time.

The ``PaymentCredentialDecryptionError`` exception type is also exposed
as a property so controllers can ``except`` on it without re-reaching
into the adapter module.
"""

from __future__ import annotations

from typing import Any


class PaymentEncryptionProvider:
    """Driving-side façade for the payments Fernet encryption adapter."""

    @property
    def decryption_error(self) -> type[Exception]:
        """Return the ``PaymentCredentialDecryptionError`` class.

        Lazy-imported so the controller can ``except`` on it without
        importing the adapter module itself.
        """
        from components.payments.infrastructure.adapters.encryption import (
            PaymentCredentialDecryptionError,
        )

        return PaymentCredentialDecryptionError

    def encrypt_json(self, payload: dict[str, Any] | None) -> str:
        from components.payments.infrastructure.adapters.encryption import (
            encrypt_json as _encrypt_json,
        )

        return _encrypt_json(payload)

    def decrypt_json(self, token: str) -> dict[str, Any]:
        from components.payments.infrastructure.adapters.encryption import (
            decrypt_json as _decrypt_json,
        )

        return _decrypt_json(token)


_default = PaymentEncryptionProvider()


def get_encryption_provider() -> PaymentEncryptionProvider:
    """Return the default provider — composition root for the payments
    Fernet encryption adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default

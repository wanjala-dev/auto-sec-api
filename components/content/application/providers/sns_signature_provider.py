"""Provider for the SNS signature verifier.

The public subscriber controller verifies inbound SES→SNS payloads
before touching the DB. To respect the EA controller→infrastructure
boundary the controller goes through this provider rather than
importing from ``components.content.infrastructure.services`` directly.

The ``SnsSignatureError`` exception class is exposed via a module-level
``__getattr__`` so callers can still write ``except SnsSignatureError:``
while keeping the infrastructure import lazy. Importing the attribute
triggers the lazy load on first access.
"""

from __future__ import annotations

from typing import Any


class SnsSignatureProvider:
    """Driving-side façade for the SNS signature verifier."""

    def verify(
        self,
        payload: dict[str, Any],
        *,
        expected_topic_arn: str | None = None,
    ) -> None:
        """Verify an SNS notification payload. Raises ``SnsSignatureError``
        on failure."""
        from components.content.infrastructure.services.sns_signature_verifier import (
            verify_sns_signature,
        )

        verify_sns_signature(payload, expected_topic_arn=expected_topic_arn)

    @property
    def error_class(self) -> type[Exception]:
        """Return the ``SnsSignatureError`` exception class."""
        from components.content.infrastructure.services.sns_signature_verifier import (
            SnsSignatureError,
        )

        return SnsSignatureError


_default = SnsSignatureProvider()


def get_sns_signature_provider() -> SnsSignatureProvider:
    """Return the default provider. Override via monkeypatch in tests."""
    return _default


def __getattr__(name: str):
    """Lazy module-level access to ``SnsSignatureError`` so callers can
    still write ``from ...sns_signature_provider import SnsSignatureError``
    without dragging the infrastructure module in at import time."""
    if name == "SnsSignatureError":
        from components.content.infrastructure.services.sns_signature_verifier import (
            SnsSignatureError,
        )

        return SnsSignatureError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

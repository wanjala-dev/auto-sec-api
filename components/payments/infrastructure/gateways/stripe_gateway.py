from __future__ import annotations

from components.payments.infrastructure.adapters import StripePaymentAdapter


class StripeGatewayAdapter:
    """Thin gateway that delegates all calls to the underlying StripePaymentAdapter.

    Uses ``__getattr__`` so new adapter methods are automatically available
    without manual pass-through boilerplate. Only override methods here if
    the gateway needs to add cross-cutting behaviour (logging, metrics, etc.)
    that the adapter itself shouldn't own.
    """

    slug = "stripe"

    def __init__(self, adapter: StripePaymentAdapter | None = None):
        self._adapter = adapter or StripePaymentAdapter()

    def __getattr__(self, name: str):
        """Delegate any attribute not defined on this class to the adapter."""
        return getattr(self._adapter, name)

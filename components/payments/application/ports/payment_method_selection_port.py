from __future__ import annotations

from typing import Any, Protocol


class PaymentMethodSelectionPort(Protocol):
    """Resolve the active payment method for a checkout context.

    Transitional note:
    This still returns the legacy payment method ORM model from the adapter
    because the surrounding donation and sponsorship flows have not been fully
    rehydrated into component-owned entities yet.
    """

    def resolve_method(
        self,
        *,
        workspace: Any,
        context: str,
        payment_method_id: str | None = None,
    ) -> Any | None: ...

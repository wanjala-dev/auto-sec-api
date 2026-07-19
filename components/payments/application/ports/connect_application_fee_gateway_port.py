from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class ConnectApplicationFeeGatewayPort(Protocol):
    """Reads the ACTUAL Connect application fee Stripe took on a charge.

    Used by the revenue-share fee handler for the one-time donation path,
    where ``checkout.session.completed`` does not expand the charge and so
    cannot carry ``application_fee_amount`` on its payload. The recurring
    (invoice) path carries the fee inline and never needs this.

    The implementation is Connect-scoped — it MUST pass ``stripe_account``
    so it reads the connected account's charge, not the platform account's.
    Application fees only exist on Connect destination/direct charges.
    """

    def retrieve_application_fee(
        self,
        *,
        payment_intent_id: str,
        stripe_account: str | None,
        currency: str | None = None,
    ) -> Decimal | None:
        """Return the application fee in MAJOR units (e.g. dollars), or None.

        ``None`` means the fee could not be determined (no charge yet, no fee
        on the charge, or a transient Stripe error). Callers MUST treat None
        as "do not record a fee" — never as zero.
        """
        ...

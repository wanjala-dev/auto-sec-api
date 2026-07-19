"""Resolve the canonical currency for a checkout against a payment method.

Order of precedence:

1. ``preferred`` — an explicitly priced currency (e.g. a recurring
   plan was created in EUR). The downstream validator catches the
   case where this disagrees with the connected account.
2. ``method.settlement_currency`` — populated at Stripe-connect time
   for accounts onboarded after the connect-time backfill landed.
3. Live ``StripeAccountCurrencyPort.resolve_default_currency()`` —
   for accounts onboarded before connect-time persistence existed.
   The result is persisted via the writer port so subsequent
   checkouts hit step 2 instead.
4. ``fallback`` — last-ditch sentinel (``"usd"``). Returned only when
   the payment method has no provider account yet.

Returned currency is uppercase ISO-4217. The caller is responsible for
lower-casing for Stripe at the boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .ports.payment_method_settlement_currency_writer_port import (
    PaymentMethodSettlementCurrencyWriterPort,
)
from .ports.stripe_account_currency_port import StripeAccountCurrencyPort

logger = logging.getLogger(__name__)


@dataclass
class SettlementCurrencyResolver:
    stripe_account_currency_port: StripeAccountCurrencyPort | None = None
    settlement_currency_writer: PaymentMethodSettlementCurrencyWriterPort | None = None

    def resolve(
        self,
        *,
        method: Any,
        preferred: str | None = None,
        fallback: str = "usd",
    ) -> str:
        if preferred:
            return preferred.upper()

        existing = getattr(method, "settlement_currency", None)
        if existing:
            return str(existing).upper()

        provider_account_id = getattr(method, "provider_account_id", None)
        if provider_account_id and self.stripe_account_currency_port is not None:
            resolved = self.stripe_account_currency_port.resolve_default_currency(
                provider_account_id
            )
            if resolved:
                self._persist(method=method, currency=resolved)
                return resolved

        logger.warning(
            "settlement_currency unresolved method_id=%s provider_account_id=%s; "
            "falling back to %s",
            getattr(method, "id", None),
            provider_account_id,
            fallback,
        )
        return fallback.upper()

    def _persist(self, *, method: Any, currency: str) -> None:
        if self.settlement_currency_writer is None:
            return
        method_id = getattr(method, "id", None)
        if method_id is None:
            return
        try:
            self.settlement_currency_writer.persist_settlement_currency(
                method_id=method_id, settlement_currency=currency
            )
        except Exception:
            logger.exception(
                "settlement_currency backfill persist failed method_id=%s",
                method_id,
            )
            return

        try:
            method.settlement_currency = currency
        except Exception:
            pass

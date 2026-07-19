"""Real Stripe implementation of StripeAccountCurrencyPort.

Calls ``stripe.Account.retrieve`` and returns the account's
``default_currency`` upper-cased. Stripe returns currency codes in
lowercase per their convention; we normalize to uppercase so the rest
of the system can compare directly against the allowlist.
"""

from __future__ import annotations

import logging

import stripe
from django.conf import settings

from ...application.ports.stripe_account_currency_port import (
    StripeAccountCurrencyPort,
)

logger = logging.getLogger(__name__)


class StripeAccountCurrencyAdapter(StripeAccountCurrencyPort):
    def resolve_default_currency(self, provider_account_id: str) -> str | None:
        if not provider_account_id:
            return None

        api_key = getattr(settings, "STRIPE_SECRET_KEY", None) or getattr(
            settings, "STRIPE_API_KEY", None
        )
        if not api_key:
            logger.warning(
                "StripeAccountCurrencyAdapter called without a configured "
                "Stripe secret key; returning None for %s.",
                provider_account_id,
            )
            return None

        try:
            account = stripe.Account.retrieve(
                provider_account_id, api_key=api_key
            )
        except stripe.error.StripeError:  # type: ignore[attr-defined]
            logger.exception(
                "Stripe rejected Account.retrieve for %s", provider_account_id
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error retrieving Stripe account %s",
                provider_account_id,
            )
            return None

        currency = getattr(account, "default_currency", None)
        if not currency:
            return None
        return str(currency).upper()

"""Reads the actual Connect application fee Stripe took on a one-time charge.

Implements ``ConnectApplicationFeeGatewayPort``. The one-time donation path
marks ``checkout.session.completed`` as processed, and that payload does not
expand the charge — so ``application_fee_amount`` is not on it. This adapter
retrieves the PaymentIntent (expanding its latest charge) on the connected
account and returns the application fee Stripe actually took.

Connect-scope boundary (payments-skill Pitfall 6): always pass
``stripe_account``. Application fees only exist on Connect destination/direct
charges — reading without the connected-account header would 404 / return the
platform account's (empty) view.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import stripe
from django.conf import settings

from components.payments.infrastructure.adapters.payment_utils import stripe_amount_to_decimal

logger = logging.getLogger(__name__)


class StripeConnectApplicationFeeAdapter:
    def retrieve_application_fee(
        self,
        *,
        payment_intent_id: str,
        stripe_account: str | None,
        currency: str | None = None,
    ) -> Decimal | None:
        if not payment_intent_id:
            return None
        api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            logger.warning(
                "revenue_share_fee_lookup_no_key payment_intent_id=%s",
                payment_intent_id,
            )
            return None
        stripe.api_key = api_key
        kwargs: dict = {"expand": ["latest_charge"]}
        if stripe_account:
            kwargs["stripe_account"] = stripe_account
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id, **kwargs)
        except stripe.error.InvalidRequestError:
            # Definitive: the PaymentIntent genuinely isn't there / not visible
            # on this account. No fee to record — returning None is correct.
            logger.warning(
                "revenue_share_fee_lookup_pi_not_found payment_intent_id=%s account_id=%s",
                payment_intent_id,
                stripe_account,
            )
            return None
        except (
            stripe.error.RateLimitError,
            stripe.error.APIConnectionError,
            stripe.error.APIError,
        ):
            # Transient: rate-limit / network blip / Stripe 5xx. Returning None
            # would PERMANENTLY drop this gift's fee (the handler treats None as
            # "record nothing" and the acks_late task then succeeds). Re-raise
            # so the task retries and the fee is recorded once Stripe recovers.
            logger.exception(
                "revenue_share_fee_lookup_transient payment_intent_id=%s account_id=%s",
                payment_intent_id,
                stripe_account,
            )
            raise
        except stripe.error.StripeError:
            # Any other definitive Stripe error (auth, permission, card) — no
            # retry would help; don't book a guessed fee.
            logger.exception(
                "revenue_share_fee_lookup_stripe_error payment_intent_id=%s account_id=%s",
                payment_intent_id,
                stripe_account,
            )
            return None

        charge = intent.get("latest_charge") if hasattr(intent, "get") else None
        if charge is None or isinstance(charge, str):
            return None
        raw_fee = charge.get("application_fee_amount")
        if raw_fee in (None, "", 0):
            return None
        return stripe_amount_to_decimal(raw_fee, currency or charge.get("currency"))

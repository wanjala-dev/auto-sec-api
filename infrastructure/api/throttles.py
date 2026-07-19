"""Payment and checkout-specific throttle classes.

These provide tighter rate limits on sensitive endpoints to prevent:
- Checkout session abuse (creating many Stripe sessions)
- Webhook replay attacks
- Donation spam
- Brute-force payment method enumeration
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class CheckoutAnonThrottle(AnonRateThrottle):
    """Tight limit for unauthenticated checkout requests."""

    scope = "checkout_anon"


class CheckoutUserThrottle(UserRateThrottle):
    """Per-user limit for authenticated checkout requests."""

    scope = "checkout_user"


class WebhookThrottle(AnonRateThrottle):
    """Rate limit for inbound payment webhooks.

    Generous but bounded — protects against replay floods while allowing
    Stripe's retry behavior (up to ~50 retries per event).
    """

    scope = "payment_webhook"


class DonationAnonThrottle(AnonRateThrottle):
    """Rate limit for unauthenticated donation submissions."""

    scope = "donation_anon"


class NewsletterSubscribeAnonThrottle(AnonRateThrottle):
    """Tight limit on the public newsletter subscribe endpoint.

    Prevents email-enumeration attacks where an attacker probes which
    addresses are already subscribed to a workspace. The endpoint
    always returns 202 regardless of whether the address is new,
    confirmed, or already-suppressed — combined with the rate limit,
    enumeration is too slow to be useful.
    """

    scope = "newsletter_subscribe_anon"


class NewsletterUnsubscribeAnonThrottle(AnonRateThrottle):
    """Slightly looser than subscribe — email clients prefetch unsubscribe
    links + subscribers retry clicks on flaky connections, so 30/min keeps
    the endpoint usable without enabling abuse."""

    scope = "newsletter_unsubscribe_anon"


class NewsletterOpenPixelAnonThrottle(AnonRateThrottle):
    """Open-tracking pixel loads (task #25). Inbox providers prefetch
    images in bursts (Apple MPP fetches every pixel at delivery), so the
    limit is generous — the endpoint is a single indexed row update."""

    scope = "newsletter_open_pixel_anon"


class SnsWebhookThrottle(AnonRateThrottle):
    """Rate limit for inbound SES SNS notifications.

    SES retries up to ~50 times per notification on transient failures,
    so the limit is generous. The endpoint verifies SNS message
    signatures before any DB write — bursts above the limit return 429
    and SES retries with backoff.
    """

    scope = "sns_webhook"

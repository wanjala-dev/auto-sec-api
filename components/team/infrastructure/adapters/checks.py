from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def stripe_subscription_settings_check(app_configs, **kwargs):
    """Validate Stripe subscription webhook configuration."""
    errors = []
    use_warning = bool(getattr(settings, "DEBUG", False))
    webhook_secret = getattr(settings, "STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET", None)
    webhook_url = (
        getattr(settings, "WORKSPACE_BILLING_WEBHOOK_URL", None)
        or getattr(settings, "SUBSCRIPTION_WEBHOOK_URL", None)
    )

    if not webhook_secret:
        message_cls = Warning if use_warning else Error
        message_id = "team.W001" if use_warning else "team.E001"
        errors.append(message_cls("STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET is not configured.", id=message_id))
    if not webhook_url:
        message_cls = Warning if use_warning else Error
        message_id = "team.W002" if use_warning else "team.E002"
        errors.append(
            message_cls(
                "WORKSPACE_BILLING_WEBHOOK_URL or SUBSCRIPTION_WEBHOOK_URL must be configured.",
                id=message_id,
            )
        )
    return errors

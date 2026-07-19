from django.apps import AppConfig


class PaymentsCLIConfig(AppConfig):
    name = 'components.payments.cli'
    label = 'payments_cli'
    verbose_name = 'Payments CLI'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self) -> None:
        # Configure SDK-level network timeouts and retries at process boot.
        # Default Stripe SDK timeout is 80s — far longer than Stripe's own
        # 10s webhook budget — and it does no automatic retries. Both are
        # bad defaults for a payment-critical service. Tighten both here so
        # every Stripe call from this process inherits the policy.
        try:
            import stripe
            from stripe import http_client as _stripe_http_client

            stripe.max_network_retries = 2
            stripe.default_http_client = _stripe_http_client.RequestsClient(
                timeout=8,
                verify_ssl_certs=True,
            )
        except Exception:  # pragma: no cover - SDK absence
            pass

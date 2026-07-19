from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Iterable
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.utils import timezone
from stripe.error import SignatureVerificationError

from components.payments.domain.donor_tip import DonorTipBreakdown, DonorTipRequest
from components.payments.domain.errors import (
    PaymentAccountUnavailableError,
    PaymentDomainError,
    PaymentValidationError,
    ProviderUnavailableError,
)
from components.payments.domain.policies.monetization_policy import platform_fee_bps_for
from components.payments.infrastructure.adapters.base_adapter import PaymentAdapter, WebhookVerificationResult
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
)
from components.payments.infrastructure.adapters.payment_utils import decimal_to_stripe_amount
from infrastructure.persistence.workspaces.payments.models import (
    PaymentPlan,
    PaymentWebhookEndpoint,
    WorkspacePaymentMethod,
)

logger = logging.getLogger(__name__)


def _translate_stripe_checkout_error(
    exc: stripe.error.StripeError,
    *,
    workspace_id,
    account_id,
) -> PaymentDomainError:
    """Translate a raw Stripe SDK error into a typed payments domain error.

    The mapping is intentional and load-bearing (see the checkout 500 bug):

    - ``PermissionError`` / ``AuthenticationError`` — the secret key has no
      access to the connected account, the account doesn't exist, or app
      access was revoked. This is a **per-org payment-config problem**, not a
      Stripe outage. Mapped to ``PaymentAccountUnavailableError`` (a
      ``ValidationError`` → HTTP 400) so it does NOT trip the circuit breaker
      and does NOT black out the frontend (>= 500 = "backend unhealthy").
    - ``CardError`` — the donor's card was declined. ``user_message`` is
      Stripe's donor-safe text. Mapped to ``PaymentValidationError`` (→ 400).
    - ``InvalidRequestError`` — bad params we sent. Mapped to
      ``PaymentValidationError`` (→ 400); logged so we can fix the call.
    - everything else (``RateLimitError``, ``APIConnectionError``,
      ``APIError``, any other ``StripeError``) — a genuine provider-
      availability problem. Mapped to ``ProviderUnavailableError`` (an
      ``IntegrationError`` → HTTP 502) which DOES count toward the breaker
      and is retryable.

    The raw Stripe message is logged server-side ONLY — it embeds the
    secret-key prefix and the internal connected-account id, so it must never
    reach a user-facing message.
    """
    # Per-org account problem — revoked / not-onboarded / nonexistent account.
    if isinstance(exc, (stripe.error.PermissionError, stripe.error.AuthenticationError)):
        logger.exception(
            "stripe_checkout_account_unavailable workspace_id=%s account_id=%s error_type=%s",
            workspace_id,
            account_id,
            type(exc).__name__,
        )
        return PaymentAccountUnavailableError(
            "This organisation isn't able to accept payments right now — its "
            "payment account needs to be (re)connected. Please try again later "
            "or contact the organisation."
        )

    # Card declined — donor-facing problem, Stripe gives us safe copy.
    if isinstance(exc, stripe.error.CardError):
        logger.info(
            "stripe_checkout_card_declined workspace_id=%s account_id=%s code=%s",
            workspace_id,
            account_id,
            getattr(exc, "code", None),
        )
        safe_message = getattr(exc, "user_message", None) or "Your card was declined."
        return PaymentValidationError(safe_message)

    # Bad params we sent — our bug, but a 400 to the donor (not a 500).
    if isinstance(exc, stripe.error.InvalidRequestError):
        logger.exception(
            "stripe_checkout_invalid_request workspace_id=%s account_id=%s param=%s",
            workspace_id,
            account_id,
            getattr(exc, "param", None),
        )
        return PaymentValidationError(
            "We couldn't start this payment. Please check the details and try again."
        )

    # Rate limit / connection / API errors — genuine provider availability
    # failures. These SHOULD count toward the circuit breaker and are retryable.
    logger.exception(
        "stripe_checkout_provider_unavailable workspace_id=%s account_id=%s error_type=%s",
        workspace_id,
        account_id,
        type(exc).__name__,
    )
    return ProviderUnavailableError("stripe")


def _derive_checkout_idempotency_key(
    *,
    workspace_id,
    plan_id,
    client_reference_id,
) -> str:
    """Derive a Stripe idempotency key bucketed by the current hour.

    Stripe stores idempotency keys for 24h. Bucketing by hour means a
    user-double-click within the same hour collapses to one Checkout Session,
    while a fresh attempt an hour later (e.g. retried after the user closed
    the tab) gets a new session — which is what users expect.
    """
    hour_bucket = int(time.time() // 3600)
    raw = "|".join(
        str(part) if part is not None else ""
        for part in (
            "checkout",
            workspace_id,
            plan_id,
            client_reference_id,
            hour_bucket,
        )
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"co_{digest[:48]}"


class StripePaymentAdapter(PaymentAdapter):
    slug = "stripe"

    @staticmethod
    def _extract_event_account(event: object) -> str | None:
        if isinstance(event, dict):
            return event.get("account")
        return getattr(event, "account", None)

    def verify_webhook(
        self,
        request: HttpRequest,
        endpoint_name: str | None,
        candidate_methods: Iterable[WorkspacePaymentMethod],
    ) -> WebhookVerificationResult:
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        if not sig_header:
            raise ValueError("Missing Stripe signature header")

        account_id = request.META.get("HTTP_STRIPE_ACCOUNT") or request.GET.get("account")
        secret_hint = request.GET.get("secret")
        if getattr(request, "force_platform_webhook", False):
            account_id = None
            secret_hint = None
        global_secret = getattr(settings, "STRIPE_WEBHOOK_KEY", "") or getattr(
            settings, "STRIPE_CONNECT_WEBHOOK_SECRET", ""
        )
        if endpoint_name == "donations":
            donations_secret = getattr(
                settings, "STRIPE_CONNECT_DONATIONS_WEBHOOK_SECRET", ""
            )
            if donations_secret:
                global_secret = donations_secret
        if endpoint_name == "team_subscriptions" and not global_secret:
            global_secret = getattr(settings, "STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET", "")

        methods_qs = candidate_methods
        if hasattr(methods_qs, "select_related"):
            # Avoid N+1 on `method.workspace` access in the loop below.
            methods_qs = methods_qs.select_related("workspace", "provider")
        if account_id:
            methods_qs = methods_qs.filter(provider_account_id=account_id)
        if secret_hint:
            methods_qs = methods_qs.filter(webhooks__signing_secret=secret_hint)
        if not account_id and not secret_hint:
            methods_qs = methods_qs.filter(webhooks__status=PaymentWebhookEndpoint.STATUS_ACTIVE)

        if global_secret:
            try:
                event = stripe.Webhook.construct_event(payload, sig_header, global_secret)
                # event.account is the authoritative connected account for
                # Connect events. Prefer it over the (rarely present)
                # Stripe-Account header — incoming Connect webhooks do not
                # carry the header, only the payload's account field.
                event_account = self._extract_event_account(event)
                effective_account = event_account or account_id
                method = self._resolve_method_by_account(
                    effective_account, candidate_methods
                )
                workspace = method.workspace if method else None
                credentials = read_payment_method_credentials(method) if method else {}
                api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
                return WebhookVerificationResult(
                    event=event,
                    method=method,
                    workspace=workspace,
                    account_id=effective_account,
                    api_key=api_key,
                )
            except (ValueError, SignatureVerificationError):
                pass

        # `.distinct()` is required because the `webhooks__…` joins above can
        # multiply rows. Iterate once; per-row work is bounded.
        candidate_iter = methods_qs.distinct() if hasattr(methods_qs, "distinct") else methods_qs
        for method in candidate_iter:
            webhooks = method.webhooks.filter(status=PaymentWebhookEndpoint.STATUS_ACTIVE)
            if endpoint_name:
                webhooks = webhooks.filter(name=endpoint_name)
            for webhook in webhooks:
                try:
                    event = stripe.Webhook.construct_event(payload, sig_header, webhook.signing_secret)
                    # Per-method webhook secrets are commonly shared across
                    # Connect accounts (Stripe signs every event delivered
                    # to a given endpoint with the same secret). The method
                    # whose secret happened to verify is NOT necessarily
                    # the method for the connected account that triggered
                    # the event. Always re-route by event.account when
                    # present so Connect events don't leak across
                    # workspaces.
                    event_account = self._extract_event_account(event)
                    effective_method = method
                    effective_account = method.provider_account_id
                    if event_account and event_account != method.provider_account_id:
                        correct = self._resolve_method_by_account(
                            event_account, candidate_methods
                        )
                        if correct is not None:
                            effective_method = correct
                            effective_account = event_account
                        else:
                            # Connect event for an account we don't have
                            # a method for. Surface event.account so
                            # downstream Stripe API calls use the right
                            # stripe_account header, but don't attribute
                            # the event to the wrong workspace.
                            effective_method = None
                            effective_account = event_account
                    credentials = (
                        read_payment_method_credentials(effective_method)
                        if effective_method
                        else {}
                    )
                    api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
                    if not api_key:
                        raise ValueError("Stripe secret key is required for Stripe operations.")
                    return WebhookVerificationResult(
                        event=event,
                        method=effective_method,
                        workspace=effective_method.workspace if effective_method else None,
                        account_id=effective_account,
                        api_key=api_key,
                    )
                except (ValueError, SignatureVerificationError):
                    continue

        raise ValueError("Unable to verify Stripe webhook for provided method/account.")

    @staticmethod
    def _resolve_method_by_account(
        account: str | None,
        candidate_methods: Iterable[WorkspacePaymentMethod],
    ) -> WorkspacePaymentMethod | None:
        if not account:
            return None
        if hasattr(candidate_methods, "filter"):
            return candidate_methods.filter(provider_account_id=account).first()
        return next(
            (
                m
                for m in candidate_methods
                if getattr(m, "provider_account_id", None) == account
            ),
            None,
        )

    # Checkout creation ---------------------------------------------------
    def create_checkout_session(
        self,
        method: WorkspacePaymentMethod,
        plan: PaymentPlan | None,
        *,
        amount: Decimal | None,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None,
        customer_id: str | None = None,
        client_reference_id: str | None,
        metadata: dict | None,
        idempotency_key: str | None = None,
        donor_tip: "DonorTipRequest | None" = None,
    ):
        if method.provider.slug != "stripe":
            raise ImproperlyConfigured("Stripe adapter received non-Stripe method.")

        credentials = read_payment_method_credentials(method)
        api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise ImproperlyConfigured("Stripe secret key is required for Stripe operations.")
        stripe.api_key = api_key
        publishable_key = credentials.get("publishable_key") or getattr(settings, "STRIPE_PUBLISHABLE_KEY", None)

        account_id = method.provider_account_id or credentials.get("account_id")

        metadata = metadata or {}
        metadata.setdefault("method_id", str(method.id))
        metadata.setdefault("workspace_id", str(method.workspace_id))
        if plan:
            metadata.setdefault("plan_id", str(plan.id))
            metadata.setdefault("context", plan.context)

        line_items = []
        session_kwargs = {
            "payment_method_types": ["card"],
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if account_id:
            session_kwargs["stripe_account"] = account_id
        if customer_id:
            session_kwargs["customer"] = customer_id
        elif customer_email:
            session_kwargs["customer_email"] = customer_email
            # customer_creation="always" ensures Stripe saves the payment
            # method for future use. Only valid in payment mode — for
            # subscriptions Stripe creates the customer automatically.
            is_subscription = plan and getattr(plan, "is_recurring", False)
            if not is_subscription:
                session_kwargs["customer_creation"] = "always"
        if client_reference_id:
            session_kwargs["client_reference_id"] = client_reference_id

        # Platform application fee (bps) for Connect donation charges. The SOURCE
        # is the donation-monetization policy keyed on the workspace's mode — NOT
        # the static method column — so the modes stay mutually exclusive:
        #   tip           -> 0 bps (the donor tip IS the fee, applied below)
        #   revenue_share -> workspace.revenue_share_bps (flat %)
        #   none          -> 0 bps
        # Only meaningful when stripe_account is set (Connect destination charges).
        # Default mode 'tip' + default rate => 0 bps => byte-for-byte identical to
        # today for every current workspace (platform_fee_bps was 0 everywhere).
        _fee_workspace = getattr(method, "workspace", None)
        platform_fee_bps = platform_fee_bps_for(
            getattr(_fee_workspace, "donation_monetization", None),
            int(getattr(_fee_workspace, "revenue_share_bps", 0) or 0),
        )

        if plan and plan.is_recurring:
            interval = plan.interval or PaymentPlan.INTERVAL_MONTH
            interval_count = plan.interval_count or 1
            if plan.custom_amount:
                if amount is None:
                    raise ImproperlyConfigured("Recurring custom amounts require an explicit amount.")
                amount_cents = decimal_to_stripe_amount(amount, currency)
                if amount_cents is None or amount_cents <= 0:
                    raise ImproperlyConfigured("Donation amount must be greater than zero.")
                # Source-derived label set by every checkout use case via
                # DonationPurposeResolver. Donor sees this on the Stripe
                # checkout page. plan.label is a billing schedule, not a
                # source description — fall back only when metadata is
                # absent (legacy callers; the contract enforces presence
                # for new code).
                product_name = (
                    (metadata.get("purpose") if metadata else None)
                    or (plan.label if plan else method.display_name)
                )
                price_data = {
                    "currency": currency.lower(),
                    "unit_amount": amount_cents,
                    "recurring": {"interval": interval, "interval_count": interval_count},
                }
                if plan.product_id:
                    price_data["product"] = plan.product_id
                else:
                    price_data["product_data"] = {"name": product_name}
                line_items.append({"price_data": price_data, "quantity": 1})
            else:
                self.ensure_plan_resources(method, plan)
                if not plan.price_id:
                    raise ImproperlyConfigured("Stripe price could not be created for the selected plan.")
                line_items.append({"price": plan.price_id, "quantity": 1})
            session_kwargs["mode"] = "subscription"
            session_kwargs["line_items"] = line_items
            subscription_data: dict = {"metadata": metadata}
            if account_id and platform_fee_bps > 0:
                # For subscriptions Stripe wants application_fee_percent (a
                # decimal percent, not bps). Convert: bps / 100 = percent.
                subscription_data["application_fee_percent"] = round(
                    platform_fee_bps / 100, 4
                )
            session_kwargs["subscription_data"] = subscription_data
        else:
            if plan and plan.custom_amount and amount is None:
                raise ImproperlyConfigured("Custom amounts require an explicit amount.")
            amount_source = amount if amount is not None else (plan.amount if plan else None)
            if amount_source is None:
                raise ImproperlyConfigured("One-time payments require an explicit amount.")
            amount_cents = decimal_to_stripe_amount(amount_source, currency)
            if amount_cents is None or amount_cents <= 0:
                raise ImproperlyConfigured("Donation amount must be greater than zero.")
            # Source-derived label set by every checkout use case via
            # DonationPurposeResolver. plan.label fallback retained for
            # legacy callers; the contract enforces presence for new code.
            product_name = (
                (metadata.get("purpose") if metadata else None)
                or (plan.label if plan else method.display_name)
            )
            line_items.append(
                {
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": amount_cents,
                        "product_data": {"name": product_name},
                    },
                    "quantity": 1,
                }
            )
            session_kwargs["mode"] = "payment"
            payment_intent_data: dict = {"metadata": metadata}
            application_fee_cents = 0
            if account_id and platform_fee_bps > 0 and amount_cents:
                # One-time charge: Stripe wants application_fee_amount in
                # the smallest currency unit (cents).
                application_fee_cents += (amount_cents * platform_fee_bps) // 10000
            # Donor tip — ONLY on one-time Connect (direct) charges. The tip
            # is a donor-chosen application_fee on top of the donation; the
            # support line carries the tip + optional fee coverage so the org
            # keeps its full donation. Recurring tips are out of scope (a tip
            # on a subscription would recur — a separate product decision).
            # See components/payments/domain/donor_tip.py + DONOR_TIPS plan.
            if account_id and donor_tip is not None and donor_tip.is_active and amount_source is not None:
                breakdown = DonorTipBreakdown.compute(
                    donation=Decimal(amount_source),
                    tip=donor_tip.tip,
                    currency=currency,
                    cover_fees=donor_tip.cover_fees,
                    processing_fee_rate=Decimal(str(getattr(settings, "STRIPE_PROCESSING_FEE_RATE", "0.029"))),
                    processing_fee_fixed=Decimal(str(getattr(settings, "STRIPE_PROCESSING_FEE_FIXED", "0.30"))),
                )
                # Stamp the TRUE donation + tip into metadata so the webhook
                # records the org's real gift (not the inflated charge total,
                # which now includes the support line) and the tip separately.
                # Stripe metadata values must be strings. `metadata` is the
                # same dict carried on the session + payment_intent_data.
                metadata["donation_amount"] = str(breakdown.donation)
                metadata["tip_amount"] = str(breakdown.tip)
                metadata["tip_fee_coverage"] = str(breakdown.fee_coverage)
                metadata["tip_cover_fees"] = "true" if breakdown.cover_fees else "false"
                support_amount = breakdown.tip + breakdown.fee_coverage
                support_cents = decimal_to_stripe_amount(support_amount, currency)
                if support_cents and support_cents > 0:
                    line_items.append(
                        {
                            "price_data": {
                                "currency": currency.lower(),
                                "unit_amount": support_cents,
                                "product_data": {"name": "Platform support (optional)"},
                            },
                            "quantity": 1,
                        }
                    )
                tip_cents = decimal_to_stripe_amount(breakdown.tip, currency)
                if tip_cents:
                    application_fee_cents += tip_cents
            session_kwargs["line_items"] = line_items
            if account_id and application_fee_cents > 0:
                payment_intent_data["application_fee_amount"] = application_fee_cents
            session_kwargs["payment_intent_data"] = payment_intent_data

        # Always attach metadata to the session itself so the webhook router
        # can read ``session.metadata.context`` regardless of payment mode.
        # subscription_data / payment_intent_data ALSO carry it for Stripe
        # objects created downstream.
        if metadata:
            session_kwargs["metadata"] = metadata

        create_kwargs = dict(session_kwargs)
        # Always pass an idempotency_key. If the caller didn't supply one, derive
        # a deterministic key from (workspace, plan, client_ref, hour bucket).
        # This collapses double-submits within the same hour to the same Stripe
        # session — Stripe's own 24h idempotency window then naturally GCs it.
        # Different hour → fresh session, which matches user expectations for
        # retries hours later.
        effective_key = idempotency_key or _derive_checkout_idempotency_key(
            workspace_id=method.workspace_id,
            plan_id=getattr(plan, "id", None),
            client_reference_id=client_reference_id,
        )
        if effective_key:
            create_kwargs["idempotency_key"] = effective_key
        try:
            session = stripe.checkout.Session.create(**create_kwargs)
        except stripe.error.StripeError as exc:
            # Translate raw Stripe SDK errors into typed payments domain errors
            # so the DRF exception handler returns a clean 4xx/5xx instead of a
            # raw 500 to the donor. The translation also decides whether the
            # ResilientGateway should trip the circuit breaker (provider-
            # availability errors only) — a revoked account or a declined card
            # is per-request, not "Stripe is down".
            raise _translate_stripe_checkout_error(
                exc,
                workspace_id=method.workspace_id,
                account_id=account_id,
            ) from exc
        session_id = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
        if not session_id:
            raise ValueError("Stripe session id missing from checkout response.")
        return {
            "provider": "stripe",
            "sessionId": session_id,
            "accountId": account_id,
            "publishableKey": publishable_key,
        }

    # Plan synchronisation ------------------------------------------------
    def ensure_plan_resources(self, method: WorkspacePaymentMethod, plan: PaymentPlan) -> None:
        if method.provider.slug != "stripe":
            return
        if plan.custom_amount:
            return

        credentials = read_payment_method_credentials(method)
        api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise ImproperlyConfigured("Stripe secret key is required for Stripe operations.")
        stripe.api_key = api_key

        account_id = method.provider_account_id or credentials.get("account_id")

        amount_cents = decimal_to_stripe_amount(plan.amount, plan.currency)
        if amount_cents is None or amount_cents <= 0:
            raise ValueError("Plan amount must be greater than zero for Stripe price creation.")
        currency = plan.currency.lower()

        if plan.recipient:
            recipient = plan.recipient
            recipient_name = " ".join(
                part for part in [recipient.first_name, recipient.last_name] if part
            ).strip() or str(recipient.id)
            product_name = f"{recipient_name} Sponsorship"
        else:
            workspace_name = method.workspace.workspace_name or "Workspace"
            product_name = f"{workspace_name} – {plan.label}"

        product_metadata = {
            "workspace_id": str(method.workspace_id),
            "method_id": str(method.id),
            "plan_id": str(plan.id),
            "context": plan.context,
        }
        if plan.recipient_id:
            product_metadata["recipient_id"] = str(plan.recipient_id)
            product_metadata["recipient_id"] = str(plan.recipient_id)

        if plan.product_id:
            try:
                stripe.Product.modify(
                    plan.product_id,
                    name=product_name,
                    metadata=product_metadata,
                    **({"stripe_account": account_id} if account_id else {}),
                )
            except stripe.error.InvalidRequestError:
                plan.product_id = ""

        if not plan.product_id:
            product = stripe.Product.create(
                name=product_name,
                metadata=product_metadata,
                **({"stripe_account": account_id} if account_id else {}),
            )
            plan.product_id = product.id

        price_needs_refresh = False
        if plan.price_id:
            try:
                price = stripe.Price.retrieve(plan.price_id, stripe_account=account_id)
                same_amount = int(price["unit_amount"]) == amount_cents
                same_currency = price["currency"].lower() == currency
                if plan.is_recurring:
                    recurring = price.get("recurring", {}) or {}
                    interval = recurring.get("interval")
                    interval_count = recurring.get("interval_count", 1)
                    same_interval = interval == (plan.interval or PaymentPlan.INTERVAL_MONTH)
                    same_interval_count = interval_count == (plan.interval_count or 1)
                else:
                    same_interval = bool(price.get("type") == "one_time")
                    same_interval_count = True
                if not (same_amount and same_currency and same_interval and same_interval_count):
                    price_needs_refresh = True
            except stripe.error.InvalidRequestError:
                price_needs_refresh = True
        else:
            price_needs_refresh = True

        if price_needs_refresh and plan.price_id:
            try:
                stripe.Price.modify(
                    plan.price_id,
                    active=False,
                    **({"stripe_account": account_id} if account_id else {}),
                )
            except stripe.error.InvalidRequestError:
                pass
            archived = plan.metadata.get("archived_prices", [])
            archived.append(plan.price_id)
            plan.metadata["archived_prices"] = archived
            plan.price_id = ""

        if not plan.price_id:
            price_kwargs = {
                "unit_amount": amount_cents,
                "currency": currency,
                "product": plan.product_id,
            }
            if plan.is_recurring:
                interval = plan.interval or PaymentPlan.INTERVAL_MONTH
                price_kwargs["recurring"] = {
                    "interval": interval,
                    "interval_count": plan.interval_count or 1,
                }
            price = stripe.Price.create(
                **price_kwargs,
                **({"stripe_account": account_id} if account_id else {}),
            )
            plan.price_id = price.id

        plan.metadata["synced_at"] = timezone.now().isoformat()
        plan.save(update_fields=["product_id", "price_id", "metadata", "updated_at"])

    def capture_payment(
        self,
        method: WorkspacePaymentMethod,
        identifier: str,
        *,
        amount=None,
        currency: str = "usd",
        metadata=None,
    ) -> dict:
        raise NotImplementedError("Stripe capture handled via webhooks.")

    # ------------------------------------------------------------------
    # Customer & setup management
    # ------------------------------------------------------------------

    def create_customer(
        self, *, email: str, name: str | None = None, stripe_account: str | None = None
    ) -> dict:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        kwargs = {}
        if stripe_account:
            kwargs["stripe_account"] = stripe_account
        try:
            customer = stripe.Customer.create(email=email, name=name or email, **kwargs)
            return {"id": customer.id, "email": email}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

    def create_setup_intent(
        self, *, customer_id: str, payment_method_types: list[str] | None = None
    ) -> dict:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            intent = stripe.SetupIntent.create(
                customer=customer_id,
                payment_method_types=payment_method_types or ["card"],
            )
            return {"client_secret": intent.client_secret, "customer_id": customer_id}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

    def verify_account(self, *, api_key: str, account_id: str | None = None) -> dict:
        stripe.api_key = api_key
        try:
            if account_id:
                account = stripe.Account.retrieve(account_id)
                return {
                    "ok": True,
                    "charges_enabled": getattr(account, "charges_enabled", False),
                    "details_submitted": getattr(account, "details_submitted", False),
                    "account_id": account_id,
                }
            else:
                balance = stripe.Balance.retrieve()
                return {"ok": True, "available": True}
        except stripe.error.StripeError as exc:
            return {"ok": False, "error": str(exc)}

    def register_webhook_endpoint(
        self,
        *,
        url: str,
        enabled_events: list[str],
        api_key: str,
        description: str = "",
        connect: bool = False,
    ) -> dict:
        stripe.api_key = api_key
        try:
            kwargs = {
                "url": url,
                "enabled_events": enabled_events,
                "api_key": api_key,
                "description": description,
            }
            if connect:
                kwargs["connect"] = True
            endpoint = stripe.WebhookEndpoint.create(**kwargs)
            return {"secret": endpoint.get("secret", ""), "id": endpoint.get("id", "")}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Payment method management (sponsor-facing)
    # ------------------------------------------------------------------

    def list_customer_payment_methods(
        self,
        *,
        customer_id: str,
        method_type: str = "card",
        limit: int = 10,
        stripe_account: str | None = None,
    ) -> list[dict]:
        """List saved payment methods for a Stripe customer."""
        stripe.api_key = settings.STRIPE_SECRET_KEY
        kwargs = {}
        if stripe_account:
            kwargs["stripe_account"] = stripe_account
        try:
            methods = stripe.PaymentMethod.list(
                customer=customer_id, type=method_type, limit=limit, **kwargs
            )
            return [pm.to_dict() for pm in methods.data]
        except stripe.error.StripeError:
            return []

    def retrieve_customer(
        self,
        *,
        customer_id: str,
        stripe_account: str | None = None,
    ) -> dict:
        """Retrieve a Stripe customer."""
        stripe.api_key = settings.STRIPE_SECRET_KEY
        kwargs = {}
        if stripe_account:
            kwargs["stripe_account"] = stripe_account
        try:
            result = stripe.Customer.retrieve(customer_id, **kwargs)
            return result.to_dict() if hasattr(result, "to_dict") else {"id": customer_id}
        except stripe.error.StripeError:
            return {}

    def retrieve_payment_method(self, *, payment_method_id: str) -> dict:
        """Retrieve a payment method's details (including its customer)."""
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            result = stripe.PaymentMethod.retrieve(payment_method_id)
            return result.to_dict() if hasattr(result, "to_dict") else {"id": payment_method_id}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

    def detach_payment_method(self, *, payment_method_id: str) -> dict:
        """Detach a payment method from its customer."""
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            result = stripe.PaymentMethod.detach(payment_method_id)
            return result.to_dict() if hasattr(result, "to_dict") else {"id": payment_method_id}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

    def set_default_payment_method(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        stripe_account: str | None = None,
    ) -> dict:
        """Set a payment method as the customer's default."""
        stripe.api_key = settings.STRIPE_SECRET_KEY
        kwargs = {}
        if stripe_account:
            kwargs["stripe_account"] = stripe_account
        try:
            result = stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
                **kwargs,
            )
            return result.to_dict() if hasattr(result, "to_dict") else {"id": customer_id}
        except stripe.error.StripeError as exc:
            return {"error": str(exc)}

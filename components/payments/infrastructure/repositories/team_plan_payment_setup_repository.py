from __future__ import annotations

import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import router, transaction
from django.utils.text import slugify

from components.payments.domain.errors import (
    PaymentConfigurationError,
    PaymentValidationError,
    SubscriptionError,
    UnsupportedPaymentProviderError,
)
from components.payments.infrastructure.adapters.payment_method_credentials import (
    read_payment_method_credentials,
    write_payment_method_credentials,
)
from components.payments.application.ports.payment_gateway_provider_port import (
    PaymentGatewayProviderPort,
)
from components.payments.application.ports.team_plan_payment_setup_port import (
    TeamPlanPaymentSetupPort,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.payments.models import (
    PaymentPlan,
    PaymentProvider,
    PaymentWebhookEndpoint,
    WorkspacePaymentMethod,
)

logger = logging.getLogger(__name__)


class TeamPlanPaymentSetupRepository(TeamPlanPaymentSetupPort):
    """Infrastructure adapter for managed team-plan payment setup."""

    def __init__(self, gateway_provider: PaymentGatewayProviderPort):
        self.gateway_provider = gateway_provider

    def ensure_subscription_payment_method(self, *, workspace):
        if workspace is None:
            raise PaymentValidationError("Workspace is required to provision subscription payment method.")

        provider = PaymentProvider.objects.filter(slug="stripe").first()
        if not provider:
            raise PaymentConfigurationError("Stripe payment provider is not configured.")

        # Lock the workspace row before checking for an existing managed
        # subscription method, so two concurrent callers can't both pass
        # the "not method" check and create duplicate rows. This was
        # observed in prod where workspaces ended up with two
        # "Workspace Subscription" methods created in the same request
        # (timestamps matched to the microsecond). select_for_update
        # serialises the get-or-create at the row level.
        # ``Workspace`` is routed to a tenant database by TenantRouter, so the
        # atomic block must open on that same connection — a bare
        # ``transaction.atomic()`` only begins a transaction on ``default`` and
        # ``select_for_update`` then raises "cannot be used outside of a
        # transaction" on the tenant connection. Same fix as donation_payment_repository.py.
        db_alias = router.db_for_write(type(workspace))
        with transaction.atomic(using=db_alias):
            type(workspace).objects.using(db_alias).select_for_update().filter(
                id=workspace.id
            ).first()

            method = (
                workspace.payment_methods.filter(
                    metadata__managed_subscription=True,
                    is_deleted=False,
                )
                .select_related("provider")
                .first()
            )

            if not method:
                method = WorkspacePaymentMethod.objects.create(
                    workspace=workspace,
                    provider=provider,
                    display_name="Workspace Subscription",
                    status=WorkspacePaymentMethod.STATUS_ACTIVE,
                    enabled_contexts=[PaymentPlan.CONTEXT_TEAM_PLAN],
                    metadata={"managed_subscription": True},
                    created_by=getattr(workspace, "workspace_owner", None),
                    updated_by=getattr(workspace, "workspace_owner", None),
                )
            else:
                updates = []
                contexts = set(method.enabled_contexts or [])
                if PaymentPlan.CONTEXT_TEAM_PLAN not in contexts:
                    contexts.add(PaymentPlan.CONTEXT_TEAM_PLAN)
                    method.enabled_contexts = list(contexts)
                    updates.append("enabled_contexts")
                if method.provider_account_id:
                    method.provider_account_id = ""
                    updates.append("provider_account_id")
                if method.status != WorkspacePaymentMethod.STATUS_ACTIVE:
                    method.status = WorkspacePaymentMethod.STATUS_ACTIVE
                    updates.append("status")
                if updates:
                    method.save(update_fields=[*updates, "updated_at"])

        creds = read_payment_method_credentials(method)
        credentials_dirty = False
        if creds.get("account_id"):
            creds.pop("account_id", None)
            credentials_dirty = True
        secret_key = creds.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
        if secret_key and not creds.get("secret_key"):
            creds["secret_key"] = secret_key
            credentials_dirty = True
        if credentials_dirty:
            write_payment_method_credentials(method, creds)
            method.save(update_fields=["encrypted_credentials", "credentials_updated_at", "updated_at"])

        webhook_secret = getattr(settings, "STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET", None)
        webhook_url = (
            getattr(settings, "WORKSPACE_BILLING_WEBHOOK_URL", None)
            or getattr(settings, "SUBSCRIPTION_WEBHOOK_URL", "")
            or ""
        )
        if webhook_secret:
            PaymentWebhookEndpoint.objects.update_or_create(
                method=method,
                name="team_subscriptions",
                defaults={
                    "url": webhook_url,
                    "signing_secret": webhook_secret,
                    "status": PaymentWebhookEndpoint.STATUS_ACTIVE,
                },
            )
        else:
            logger.warning("STRIPE_SUBSCRIPTIONS_WEBHOOK_SECRET is not configured.")

        return method

    def ensure_platform_customer(
        self,
        *,
        workspace,
        method,
        email: str | None = None,
        name: str | None = None,
    ) -> str:
        if not workspace:
            raise PaymentValidationError("Workspace is required to provision a Stripe customer.")
        if not method:
            raise PaymentValidationError("Payment method is required to provision a Stripe customer.")

        if workspace.stripe_customer_id:
            Team.objects.filter(workspace=workspace).exclude(
                stripe_customer_id=workspace.stripe_customer_id,
            ).update(stripe_customer_id=workspace.stripe_customer_id)
            return workspace.stripe_customer_id

        credentials = read_payment_method_credentials(method)
        api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise PaymentConfigurationError("Stripe secret key is required to create a customer.")

        stripe.api_key = api_key
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={
                    "workspace_id": str(workspace.id),
                    "workspace_name": workspace.workspace_name or "",
                    "context": "team_plan",
                },
            )
        except stripe.error.StripeError as exc:
            logger.exception(
                "Stripe customer creation failed for workspace %s: %s",
                workspace.id,
                exc,
            )
            raise SubscriptionError("Unable to create Stripe customer.") from exc

        customer_id = (
            customer.get("id")
            if isinstance(customer, dict)
            else getattr(customer, "id", None)
        )
        if not customer_id:
            raise SubscriptionError("Stripe customer creation failed.")

        workspace.__class__.objects.filter(id=workspace.id).update(stripe_customer_id=customer_id)
        Team.objects.filter(workspace=workspace).update(stripe_customer_id=customer_id)
        return customer_id

    def ensure_team_plan_payment_plan(
        self,
        *,
        workspace,
        plan,
        method,
        currency_override: str | None = None,
    ):
        if not plan or plan.price <= 0:
            return None

        currency_value = (
            currency_override
            or plan.currency
            or getattr(settings, "STRIPE_DEFAULT_CURRENCY", "usd")
            or "usd"
        )
        currency = str(currency_value).lower()
        slug = slugify(plan.title) or f"plan-{plan.id}"
        interval_value = (plan.billing_interval or PaymentPlan.INTERVAL_MONTH).lower()
        allowed_intervals = {choice[0] for choice in PaymentPlan.INTERVAL_CHOICES}
        if interval_value not in allowed_intervals:
            interval_value = PaymentPlan.INTERVAL_MONTH
        interval_count = plan.interval_count or 1
        defaults = {
            "label": plan.title,
            "amount": Decimal(plan.price),
            "currency": currency,
            "interval": interval_value,
            "interval_count": interval_count,
            "is_recurring": True,
            "custom_amount": False,
            "sort_order": 0,
            "is_active": True,
        }

        payment_plan, created = PaymentPlan.objects.get_or_create(
            method=method,
            context=PaymentPlan.CONTEXT_TEAM_PLAN,
            slug=slug,
            recipient=None,
            defaults=defaults,
        )

        updates = []
        managed_price_id = None
        if plan.title.lower() == "basic":
            managed_price_id = getattr(settings, "STRIPE_BASIC_PRICE_ID", None)
        elif plan.title.lower() == "pro":
            managed_price_id = getattr(settings, "STRIPE_PRO_PRICE_ID", None)
        if managed_price_id and payment_plan.price_id != managed_price_id:
            payment_plan.price_id = managed_price_id
            updates.append("price_id")
        if not created:
            amount = Decimal(plan.price)
            if payment_plan.label != plan.title:
                payment_plan.label = plan.title
                updates.append("label")
            if payment_plan.amount != amount:
                payment_plan.amount = amount
                updates.append("amount")
            if payment_plan.currency != currency:
                payment_plan.currency = currency
                updates.append("currency")
            if payment_plan.interval != interval_value:
                payment_plan.interval = interval_value
                updates.append("interval")
            if payment_plan.interval_count != interval_count:
                payment_plan.interval_count = interval_count
                updates.append("interval_count")
            if not payment_plan.is_recurring:
                payment_plan.is_recurring = True
                updates.append("is_recurring")
            if payment_plan.custom_amount:
                payment_plan.custom_amount = False
                updates.append("custom_amount")
            if not payment_plan.is_active:
                payment_plan.is_active = True
                updates.append("is_active")

        metadata = payment_plan.metadata or {}
        if metadata.get("team_plan_id") != str(plan.id):
            metadata["team_plan_id"] = str(plan.id)
            payment_plan.metadata = metadata
            updates.append("metadata")

        if updates:
            payment_plan.save(update_fields=[*set(updates), "updated_at"])

        try:
            gateway = self.gateway_provider.get_gateway_for_provider(method.provider.slug)
        except UnsupportedPaymentProviderError:
            return payment_plan

        if method.provider.slug == "stripe" and not getattr(settings, "STRIPE_SECRET_KEY", None):
            logger.warning("Skipping Stripe plan provisioning: STRIPE_SECRET_KEY not configured")
            return payment_plan

        gateway.ensure_plan_resources(method, payment_plan)
        return payment_plan

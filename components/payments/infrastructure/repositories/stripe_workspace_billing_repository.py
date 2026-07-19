from __future__ import annotations

import logging

import stripe
from django.conf import settings

from components.payments.application.providers.team_plan_payment_setup_provider import (
    TeamPlanPaymentSetupProvider,
)
from components.payments.domain.errors import (
    PaymentConfigurationError,
    SubscriptionError,
)
from components.payments.application.ports.workspace_billing_port import (
    WorkspaceBillingContext,
    WorkspaceBillingPort,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace

logger = logging.getLogger(__name__)


class StripeWorkspaceBillingRepository(WorkspaceBillingPort):
    """Stripe-backed adapter for workspace billing reads and card management."""

    def __init__(self):
        self.team_plan_payment_setup = TeamPlanPaymentSetupProvider().build_service()

    @staticmethod
    def _require_api_key() -> str:
        api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise PaymentConfigurationError("STRIPE_SECRET_KEY is not configured.")
        stripe.api_key = api_key
        return api_key

    def _get_or_create_customer_id(self, *, workspace: Workspace) -> str:
        if workspace.stripe_customer_id:
            return workspace.stripe_customer_id
        if workspace.stripe_subscription_id:
            self._require_api_key()
            try:
                subscription = stripe.Subscription.retrieve(workspace.stripe_subscription_id)
            except stripe.error.StripeError as exc:
                logger.exception(
                    "Stripe subscription lookup failed for workspace %s: %s",
                    workspace.id,
                    exc,
                )
                raise SubscriptionError("Unable to load Stripe subscription for this organization.") from exc
            customer_id = subscription.get("customer") if subscription else None
            if not customer_id:
                raise SubscriptionError("Stripe subscription missing customer reference.")
            Workspace.objects.filter(id=workspace.id).update(stripe_customer_id=customer_id)
            Team.objects.filter(workspace=workspace).update(stripe_customer_id=customer_id)
            return customer_id

        method = self.team_plan_payment_setup.ensure_subscription_payment_method(workspace)
        owner = workspace.workspace_owner
        # ``workspace_owner`` is a CustomUser — the display name lives on
        # its UserProfile.name (NOT user.name, which doesn't exist), then
        # the auth user's full name. Without this the Stripe Customer is
        # created nameless. See the ``user-model`` skill.
        owner_name = None
        if owner is not None:
            profile = getattr(owner, "profile", None)
            owner_name = (getattr(profile, "name", "") or "").strip() or (
                owner.get_full_name() or ""
            ).strip() or None
        return self.team_plan_payment_setup.ensure_platform_customer(
            workspace,
            method=method,
            email=getattr(owner, "email", None),
            name=owner_name,
        )

    def get_context(self, *, workspace) -> WorkspaceBillingContext:
        self._require_api_key()
        customer_id = self._get_or_create_customer_id(workspace=workspace)
        return WorkspaceBillingContext(
            customer_id=customer_id,
            subscription_id=workspace.stripe_subscription_id,
        )

    def fetch_customer(self, *, customer_id: str) -> dict:
        self._require_api_key()
        return stripe.Customer.retrieve(customer_id)

    def fetch_subscription(self, *, subscription_id: str | None) -> dict | None:
        if not subscription_id:
            return None
        self._require_api_key()
        return stripe.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price", "default_payment_method"],
        )

    def list_payment_methods(self, *, customer_id: str) -> list[dict]:
        self._require_api_key()
        methods = stripe.PaymentMethod.list(customer=customer_id, type="card")
        return list(methods.data if methods else [])

    def list_invoices(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
        limit: int,
        starting_after: str | None,
        ending_before: str | None,
    ) -> tuple[list[dict], bool]:
        self._require_api_key()
        list_kwargs = {"customer": customer_id, "limit": limit}
        if subscription_id:
            list_kwargs["subscription"] = subscription_id
        if starting_after:
            list_kwargs["starting_after"] = starting_after
        if ending_before:
            list_kwargs["ending_before"] = ending_before
        invoices = stripe.Invoice.list(**list_kwargs)
        if hasattr(invoices, "get"):
            has_more = bool(invoices.get("has_more"))
        else:
            has_more = bool(getattr(invoices, "has_more", False))
        return list(invoices.data if invoices else []), has_more

    def preview_upcoming_invoice(
        self,
        *,
        customer_id: str,
        subscription_id: str | None,
    ) -> dict | None:
        if not subscription_id:
            return None
        self._require_api_key()
        try:
            return stripe.Invoice.upcoming(
                customer=customer_id,
                subscription=subscription_id,
            )
        except stripe.error.StripeError:
            return None

    def create_setup_intent(self, *, customer_id: str) -> dict:
        self._require_api_key()
        return stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=["card"],
            usage="off_session",
        )

    def retrieve_payment_method(self, *, payment_method_id: str) -> dict:
        self._require_api_key()
        return stripe.PaymentMethod.retrieve(payment_method_id)

    def set_default_payment_method(
        self,
        *,
        customer_id: str,
        payment_method_id: str,
        subscription_id: str | None,
    ) -> None:
        self._require_api_key()
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )
        if subscription_id:
            stripe.Subscription.modify(
                subscription_id,
                default_payment_method=payment_method_id,
            )

    def detach_payment_method(self, *, payment_method_id: str) -> None:
        self._require_api_key()
        stripe.PaymentMethod.detach(payment_method_id)

    @staticmethod
    def resolve_default_payment_method_id(
        *,
        subscription: dict | None,
        customer: dict | None,
    ) -> str | None:
        default_pm = subscription.get("default_payment_method") if subscription else None
        if hasattr(default_pm, "get"):
            default_pm = default_pm.get("id")
        if default_pm:
            return default_pm
        invoice_settings = customer.get("invoice_settings", {}) if customer else {}
        default_pm = invoice_settings.get("default_payment_method") if invoice_settings else None
        if hasattr(default_pm, "get"):
            default_pm = default_pm.get("id")
        return default_pm

    @staticmethod
    def get_publishable_key() -> str | None:
        return getattr(settings, "STRIPE_PUBLISHABLE_KEY", None)

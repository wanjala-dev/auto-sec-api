from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import stripe
from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from components.subscription.domain.entitlements import (
    EntitlementKey,
    EntitlementsResolver,
)

from components.payments.application.providers.payment_flow_state_provider import (
    PaymentFlowStateProvider,
)
from components.payments.application.providers.payment_runtime_provider import (
    make_payment_runtime_provider,
)
from components.payments.application.providers.team_plan_payment_setup_provider import (
    TeamPlanPaymentSetupProvider,
)
from components.payments.domain.errors import (
    PaymentConfigurationError,
    PaymentValidationError,
    SubscriptionError,
)
from components.payments.infrastructure.adapters.notification_dispatch_adapter import (
    NotificationDispatchAdapter,
)
from components.payments.infrastructure.adapters.orders import create_payment_order
from components.payments.application.ports.team_plan_billing_port import TeamPlanBillingPort
from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.project.models import Project
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.subscription.models import Plan
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import PaymentPlan

logger = logging.getLogger(__name__)
notification_dispatcher = NotificationDispatchAdapter()
team_plan_payment_setup = TeamPlanPaymentSetupProvider().build_service()
payment_flow_state_provider = PaymentFlowStateProvider()
mark_payment_flow_processing_use_case = payment_flow_state_provider.build_mark_processing_use_case()
finalize_failed_payment_use_case = payment_flow_state_provider.build_finalize_failed_use_case()


def _stripe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _resolve_subscription_currency(subscription) -> str | None:
    if not subscription:
        return None
    items_container = _stripe_get(subscription, "items", {}) or {}
    items = (
        items_container.get("data")
        if hasattr(items_container, "get")
        else getattr(items_container, "data", [])
    )
    items = items or []
    if not items:
        return None
    price = _stripe_get(items[0], "price")
    currency = _stripe_get(price, "currency") if price else None
    if not currency:
        return None
    return str(currency).lower()


def _default_proration_behavior(current_plan: Plan | None, next_plan: Plan | None) -> str:
    if not next_plan or not current_plan:
        return "create_prorations"
    if next_plan.price < current_plan.price:
        return "none"
    return "create_prorations"


def _cap(value: int | None) -> float:
    """Treat an unlimited (None) cap as +infinity for comparison."""
    return math.inf if value is None else value


def _is_plan_downgrade(current_plan: Plan | None, next_plan: Plan | None) -> bool:
    if not current_plan or not next_plan:
        return False
    if next_plan.price < current_plan.price:
        return True
    current = EntitlementsResolver.resolve(plan_limits=getattr(current_plan, "limits", None))
    nxt = EntitlementsResolver.resolve(plan_limits=getattr(next_plan, "limits", None))
    for key in (
        EntitlementKey.MAX_PROJECTS_PER_TEAM,
        EntitlementKey.MAX_TASKS_PER_PROJECT,
        EntitlementKey.MAX_MEMBERS_PER_TEAM,
    ):
        if _cap(nxt.limit_for(key)) < _cap(current.limit_for(key)):
            return True
    return False


def _collect_plan_overages(workspace, plan):
    overages = {}
    if not workspace or not plan:
        return overages

    entitlements = EntitlementsResolver.resolve(
        plan_limits=getattr(plan, "limits", None),
        workspace_overrides=getattr(workspace, "entitlement_overrides", None),
    )

    projects_cap = entitlements.limit_for(EntitlementKey.MAX_PROJECTS_PER_TEAM)
    if projects_cap is not None:
        teams = (
            Team.objects.filter(workspace=workspace, status=Team.ACTIVE)
            .annotate(project_count=Count("projects"))
            .filter(project_count__gt=projects_cap)
        )
        if teams.exists():
            overages["projects"] = [
                {"team_id": str(team.id), "count": team.project_count}
                for team in teams
            ]

    tasks_cap = entitlements.limit_for(EntitlementKey.MAX_TASKS_PER_PROJECT)
    if tasks_cap is not None:
        projects = (
            Project.objects.filter(workspace=workspace)
            .annotate(task_count=Count("tasks"))
            .filter(task_count__gt=tasks_cap)
        )
        if projects.exists():
            overages["tasks"] = [
                {"project_id": str(project.id), "count": project.task_count}
                for project in projects
            ]

    return overages


def _notify_plan_overages(workspace, plan, overages):
    if not overages:
        return
    owner = getattr(workspace, "workspace_owner", None)
    if not owner:
        return
    summary = []
    if overages.get("projects"):
        summary.append("projects")
    if overages.get("tasks"):
        summary.append("tasks")
    notification_dispatcher.dispatch_notification(
        actor=owner,
        workspace=workspace,
        verb=(
            f"Plan downgraded to {plan.title}. "
            f"Please reduce {', '.join(summary)} to stay within limits."
        ),
        notification_type=Notification.NotificationType.SYSTEM,
        recipients=[owner],
        metadata={
            "event": "plan.downgrade.over_limit",
            "plan_id": str(plan.id),
            "plan_title": plan.title,
            "overages": overages,
        },
        target=workspace,
    )


def _bump_feature_flags_for_plan_change() -> None:
    """Invalidate the feature-flag cache after a workspace's tier changes.

    The plan-tier layer of feature-flag resolution (and the metered-AI
    entitlement) keys off ``Workspace.plan``. When a tier changes
    (upgrade/downgrade/cancel), bump the global cache version so the new
    tier's feature set unlocks (or re-locks) on the next evaluation instead
    of waiting out the 300s TTL. Best-effort — a cache-layer hiccup must not
    fail a billing write that already committed.
    """
    try:
        from components.shared_platform.infrastructure.services.feature_flags import (
            bump_feature_flags_version,
        )

        bump_feature_flags_version()
    except Exception:  # noqa: BLE001 — cache invalidation is best-effort
        logger.exception("feature_flag cache bump failed after plan change")


class TeamPlanBillingRepository(TeamPlanBillingPort):
    """Infrastructure adapter for Stripe-backed workspace team-plan billing."""

    @staticmethod
    def _get_stripe_api_key() -> str:
        api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not api_key:
            raise PaymentConfigurationError("STRIPE_SECRET_KEY is not configured.")
        stripe.api_key = api_key
        return api_key

    def _fetch_subscription(self, subscription_id: str | None):
        if not subscription_id:
            return None
        self._get_stripe_api_key()
        return stripe.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price", "default_payment_method"],
        )

    def _ensure_stripe_price_for_plan(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
        currency_override: str | None = None,
    ) -> str | None:
        if plan.price <= 0:
            return None
        method = team_plan_payment_setup.ensure_subscription_payment_method(workspace)
        if currency_override is None and workspace.stripe_subscription_id:
            subscription = self._fetch_subscription(workspace.stripe_subscription_id)
            currency_override = _resolve_subscription_currency(subscription)
        payment_plan = team_plan_payment_setup.ensure_team_plan_payment_plan(
            workspace,
            plan=plan,
            method=method,
            currency_override=currency_override,
        )
        if not payment_plan:
            return None
        return payment_plan.price_id

    @staticmethod
    def _sync_workspace_plan_from_subscription(
        workspace: Workspace,
        plan: Plan | None,
        subscription,
    ) -> None:
        period_end = None
        period_end_ts = _stripe_get(subscription, "current_period_end")
        if subscription and period_end_ts:
            period_end = datetime.fromtimestamp(period_end_ts, tz=UTC)
            if not settings.USE_TZ:
                period_end = timezone.make_naive(period_end, timezone=UTC)

        plan_status = Workspace.PLAN_ACTIVE
        if subscription and _stripe_get(subscription, "status") in {"canceled", "unpaid"}:
            plan_status = Workspace.PLAN_CANCELED

        updates = {
            "plan_status": plan_status,
            "plan_end_date": period_end,
        }
        if plan:
            updates["plan"] = plan
        if subscription and _stripe_get(subscription, "status") == "canceled":
            updates["stripe_subscription_id"] = None
        Workspace.objects.filter(id=workspace.id).update(**updates)

        team_updates = {
            "plan_status": Team.PLAN_ACTIVE if plan_status == Workspace.PLAN_ACTIVE else Team.PLAN_CANCELED,
            "plan_end_date": period_end,
        }
        if plan:
            team_updates["plan"] = plan
        Team.objects.filter(workspace=workspace).update(**team_updates)

        # Tier (plan FK) changed → unlock/re-lock the tier's feature set now.
        if plan:
            _bump_feature_flags_for_plan_change()

    def _cancel_subscription(
        self,
        *,
        workspace: Workspace,
        plan: Plan | None = None,
    ):
        if not workspace.stripe_subscription_id:
            return None
        self._get_stripe_api_key()
        canceled = stripe.Subscription.delete(workspace.stripe_subscription_id)
        self._sync_workspace_plan_from_subscription(workspace, plan, canceled)
        return canceled

    def checkout_team_plan(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
        customer_email: str | None,
        customer_name: str | None,
        user_id: str | None,
        team: Team | None = None,
        success_url: str,
        cancel_url: str,
        proration_behavior: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        if plan.price <= 0:
            if workspace.stripe_subscription_id:
                self._cancel_subscription(workspace=workspace, plan=plan)
            else:
                self._sync_workspace_plan_from_subscription(workspace, plan, None)
            return {"status": "updated", "plan": plan.title}, 200

        method = team_plan_payment_setup.ensure_subscription_payment_method(workspace)
        subscription = None
        subscription_currency = None
        if workspace.stripe_subscription_id:
            subscription = self._fetch_subscription(workspace.stripe_subscription_id)
            if not subscription:
                raise SubscriptionError("Unable to load current subscription.")
            subscription_currency = _resolve_subscription_currency(subscription)
            customer_id = _stripe_get(subscription, "customer")
            if customer_id and not workspace.stripe_customer_id:
                Workspace.objects.filter(id=workspace.id).update(stripe_customer_id=customer_id)
                Team.objects.filter(workspace=workspace).update(stripe_customer_id=customer_id)

        payment_plan = team_plan_payment_setup.ensure_team_plan_payment_plan(
            workspace,
            plan=plan,
            method=method,
            currency_override=subscription_currency,
        )
        if not payment_plan:
            raise PaymentValidationError("Unable to resolve subscription pricing.")

        metadata = {
            "workspace_id": str(workspace.id),
            "plan_id": str(payment_plan.id),
            "team_plan_id": str(plan.id),
            "plan_title": plan.title,
            "user_id": str(user_id) if user_id is not None else "",
            "ctx": PaymentPlan.CONTEXT_TEAM_PLAN,
        }
        if team:
            metadata["team_id"] = str(team.id)

        if subscription:
            items_container = _stripe_get(subscription, "items", {}) or {}
            items = (
                items_container.get("data")
                if hasattr(items_container, "get")
                else getattr(items_container, "data", [])
            )
            items = items or []
            if not items:
                raise SubscriptionError("Subscription has no active items.")
            if not payment_plan.price_id:
                raise PaymentValidationError("Stripe price is missing for the selected plan.")

            order, attempt, gateway_metadata = create_payment_order(
                method=method,
                context=PaymentPlan.CONTEXT_TEAM_PLAN,
                plan=payment_plan,
                amount=payment_plan.amount,
                currency=payment_plan.currency,
                customer_email=customer_email,
                customer_name=customer_name,
                client_reference_id=f"workspace:{workspace.id}",
                metadata=metadata,
            )
            mark_payment_flow_processing_use_case.execute(
                order=order,
                attempt=attempt,
                gateway_reference=_stripe_get(subscription, "id") or "",
                gateway_reference_type="subscription",
            )

            subscription_metadata = _stripe_get(subscription, "metadata", {}) or {}
            subscription_metadata.update(
                {k: str(v) for k, v in (gateway_metadata or {}).items() if v is not None}
            )

            subscription_id = _stripe_get(subscription, "id")
            if not subscription_id:
                raise SubscriptionError("Stripe subscription id missing.")
            current_item_id = _stripe_get(items[0], "id")
            if not current_item_id:
                raise SubscriptionError("Subscription item id missing.")
            effective_proration = proration_behavior or _default_proration_behavior(workspace.plan, plan)
            self._get_stripe_api_key()
            try:
                stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=False,
                    proration_behavior=effective_proration,
                    items=[{"id": current_item_id, "price": payment_plan.price_id}],
                    metadata=subscription_metadata,
                )
            except stripe.error.StripeError as exc:
                finalize_failed_payment_use_case.execute(
                    order=order,
                    attempt=attempt,
                    message=str(exc),
                )
                raise

            return (
                {
                    "status": "updated",
                    "plan": plan.title,
                    "subscriptionId": subscription_id,
                    "orderId": str(order.id),
                    "proration_behavior": effective_proration,
                },
                200,
            )

        customer_id = workspace.stripe_customer_id
        if not customer_id:
            customer_id = team_plan_payment_setup.ensure_platform_customer(
                workspace,
                method=method,
                email=customer_email,
                name=customer_name,
            )

        currency = payment_plan.currency or getattr(settings, "STRIPE_DEFAULT_CURRENCY", "usd")
        checkout = make_payment_runtime_provider().create_checkout_session(
            method,
            plan=payment_plan,
            amount=None,
            currency=currency,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            customer_id=customer_id,
            client_reference_id=f"workspace:{workspace.id}",
            metadata=metadata,
            context=PaymentPlan.CONTEXT_TEAM_PLAN,
        )
        return checkout, 200

    def preview_plan_change(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
    ) -> dict[str, Any] | None:
        if not workspace.stripe_subscription_id:
            raise SubscriptionError("No active subscription to preview.")
        price_id = self._ensure_stripe_price_for_plan(workspace=workspace, plan=plan)
        if not price_id:
            raise PaymentValidationError("Plan does not have a billable price.")

        self._get_stripe_api_key()
        subscription = stripe.Subscription.retrieve(workspace.stripe_subscription_id)
        items_container = _stripe_get(subscription, "items", {}) or {}
        items = (
            items_container.get("data")
            if hasattr(items_container, "get")
            else getattr(items_container, "data", [])
        )
        items = items or []
        if not items:
            return None
        current_item_id = _stripe_get(items[0], "id")
        if not current_item_id:
            return None

        return stripe.Invoice.upcoming(
            subscription=workspace.stripe_subscription_id,
            subscription_items=[{"id": current_item_id, "price": price_id}],
        )

    def cancel_team_plan(
        self,
        *,
        workspace: Workspace,
        default_plan: Plan | None = None,
    ) -> Plan:
        plan = default_plan or Plan.objects.filter(is_default=True).first()
        if not plan:
            raise PaymentConfigurationError("Default plan not configured.")

        if workspace.stripe_subscription_id:
            self._get_stripe_api_key()
            stripe.Subscription.delete(workspace.stripe_subscription_id)

        Workspace.objects.filter(id=workspace.id).update(
            plan=plan,
            plan_status=Workspace.PLAN_CANCELED,
            plan_end_date=None,
            stripe_subscription_id=None,
        )
        Team.objects.filter(workspace=workspace).update(
            plan=plan,
            plan_status=Team.PLAN_CANCELED,
            plan_end_date=None,
            stripe_subscription_id=None,
        )
        return plan

    def apply_plan_change(
        self,
        *,
        workspace: Workspace,
        plan: Plan,
        proration_behavior: str = "create_prorations",
    ):
        if plan.price <= 0:
            if workspace.stripe_subscription_id:
                return self._cancel_subscription(workspace=workspace, plan=plan)
            self._sync_workspace_plan_from_subscription(workspace, plan, None)
            return None

        subscription = self._fetch_subscription(workspace.stripe_subscription_id)
        if not subscription:
            raise SubscriptionError("No active subscription found for this organization.")

        subscription_currency = _resolve_subscription_currency(subscription)
        new_price_id = self._ensure_stripe_price_for_plan(
            workspace=workspace,
            plan=plan,
            currency_override=subscription_currency,
        )
        if not new_price_id:
            raise PaymentValidationError("Unable to resolve Stripe price for plan.")

        items_container = _stripe_get(subscription, "items", {}) or {}
        items = (
            items_container.get("data")
            if hasattr(items_container, "get")
            else getattr(items_container, "data", [])
        )
        items = items or []
        if not items:
            raise SubscriptionError("Subscription has no items to update.")
        current_item_id = _stripe_get(items[0], "id")
        if not current_item_id:
            raise SubscriptionError("Subscription item id missing.")

        subscription_id = _stripe_get(subscription, "id")
        if not subscription_id:
            raise SubscriptionError("Subscription id missing from Stripe response.")

        stripe.Subscription.modify(
            subscription_id,
            items=[{"id": current_item_id, "price": new_price_id}],
            proration_behavior=proration_behavior,
        )

        updated = self._fetch_subscription(subscription_id)
        self._sync_workspace_plan_from_subscription(workspace, plan, updated)
        return updated

    def apply_team_plan_purchase(
        self,
        *,
        workspace,
        metadata: dict[str, Any],
        subscription_id: str | None = None,
        customer_id: str | None = None,
        period_end=None,
        method=None,
    ) -> None:
        if not workspace:
            return
        previous_plan = workspace.plan
        plan = None
        plan_id = metadata.get("plan_id")
        if plan_id:
            try:
                plan = Plan.objects.filter(id=int(plan_id)).first()
            except (TypeError, ValueError):
                plan = None
        if not plan:
            team_plan_id = metadata.get("team_plan_id")
            if team_plan_id:
                try:
                    plan = Plan.objects.filter(id=int(team_plan_id)).first()
                except (TypeError, ValueError):
                    plan = None
        if not plan:
            plan_title = metadata.get("plan_title")
            if plan_title:
                plan = Plan.objects.filter(title__iexact=plan_title).first()

        updates = {}
        if plan and workspace.plan_id != plan.id:
            updates["plan"] = plan
        if customer_id:
            updates["stripe_customer_id"] = customer_id
        if subscription_id:
            updates["stripe_subscription_id"] = subscription_id
        updates["plan_status"] = Workspace.PLAN_ACTIVE
        if period_end:
            updates["plan_end_date"] = period_end
        if method:
            updates["subscription_payment_method_id"] = method.id

        if updates:
            Workspace.objects.filter(id=workspace.id).update(**updates)

        team_updates = {}
        if plan:
            team_updates["plan"] = plan
        if "plan_status" in updates:
            team_updates["plan_status"] = Team.PLAN_ACTIVE
        if period_end:
            team_updates["plan_end_date"] = period_end
        if subscription_id:
            team_updates["stripe_subscription_id"] = subscription_id
        if team_updates:
            Team.objects.filter(workspace=workspace).update(**team_updates)

        if plan and _is_plan_downgrade(previous_plan, plan):
            overages = _collect_plan_overages(workspace, plan)
            if overages:
                _notify_plan_overages(workspace, plan, overages)

    def sync_deleted_subscription(
        self,
        *,
        workspace: Workspace,
        default_plan: Plan | None = None,
    ) -> Plan | None:
        resolved_default_plan = default_plan or Plan.objects.filter(is_default=True).first()
        if not resolved_default_plan:
            resolved_default_plan = Plan.objects.filter(title__iexact="Free").first()

        workspace_updates = {
            "plan_status": Workspace.PLAN_CANCELED,
            "plan_end_date": None,
            "stripe_subscription_id": None,
        }
        if resolved_default_plan:
            workspace_updates["plan"] = resolved_default_plan
        Workspace.objects.filter(id=workspace.id).update(**workspace_updates)

        team_updates = {
            "plan_status": Team.PLAN_CANCELED,
            "plan_end_date": None,
            "stripe_subscription_id": None,
        }
        if resolved_default_plan:
            team_updates["plan"] = resolved_default_plan
        Team.objects.filter(workspace=workspace).update(**team_updates)

        # Subscription deleted → workspace fell back to Free; re-lock paid features.
        if resolved_default_plan:
            _bump_feature_flags_for_plan_change()
        return resolved_default_plan

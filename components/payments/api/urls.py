"""Unified payments URL routing.

Consolidated routing for:
- Payment method management (CRUD via viewset)
- Payment provider listing
- Billing operations (checkout, plan changes, setup intents, webhooks)
- Public payment method listing
- Stripe Connect callbacks
- Billing routes for workspace mounting
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from components.payments.api.controller import (
    PaymentProviderViewSet,
    ProviderHealthController,
    PublicWorkspacePaymentMethodView,
    StripeConnectCallbackView,
    StripeSubscriptionWebhookController,
    WorkspaceBillingHistoryController,
    WorkspaceBillingOverviewController,
    WorkspaceBillingPlansController,
    WorkspacePaymentMethodDefaultController,
    WorkspacePaymentMethodDetailController,
    WorkspacePaymentMethodListController,
    WorkspacePaymentMethodViewSet,
    WorkspacePlanCancelController,
    WorkspacePlanChangeController,
    WorkspacePlanCheckoutController,
    WorkspacePlanPreviewController,
    WorkspaceSetupIntentController,
)

router = DefaultRouter()
router.register(r"providers", PaymentProviderViewSet, basename="payment-provider")

# Using a nested-style route without an additional dependency; DRF router
# can't build this directly so we wire the viewset manually below.
payment_method_list = WorkspacePaymentMethodViewSet.as_view({"get": "list", "post": "create"})
payment_method_detail = WorkspacePaymentMethodViewSet.as_view(
    {
        "get": "retrieve",
        "patch": "partial_update",
        "put": "update",
        "delete": "destroy",
    }
)
payment_method_set_primary = WorkspacePaymentMethodViewSet.as_view({"post": "set_primary"})
payment_method_authorize = WorkspacePaymentMethodViewSet.as_view({"post": "authorize"})
payment_method_upsert_webhook = WorkspacePaymentMethodViewSet.as_view({"post": "upsert_webhook"})
payment_method_test_connection = WorkspacePaymentMethodViewSet.as_view({"post": "test_connection"})
payment_method_plans = WorkspacePaymentMethodViewSet.as_view({"get": "manage_plans", "post": "manage_plans"})
payment_method_plan_detail = WorkspacePaymentMethodViewSet.as_view(
    {"patch": "manage_plan_detail", "delete": "manage_plan_detail"}
)

# ── Main Payments URLs (mounted at /workspaces/<ws>/payments/) ──

urlpatterns = [
    path("", include(router.urls)),
    path(
        "workspaces/<uuid:workspace_id>/methods/",
        payment_method_list,
        name="workspace-payment-method-list",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/",
        payment_method_detail,
        name="workspace-payment-method-detail",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/set-primary/",
        payment_method_set_primary,
        name="workspace-payment-method-set-primary",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/authorize/",
        payment_method_authorize,
        name="workspace-payment-method-authorize",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/webhooks/",
        payment_method_upsert_webhook,
        name="workspace-payment-method-webhooks",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/test-connection/",
        payment_method_test_connection,
        name="workspace-payment-method-test-connection",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/plans/",
        payment_method_plans,
        name="workspace-payment-method-plans",
    ),
    path(
        "workspaces/<uuid:workspace_id>/methods/<uuid:id>/plans/<uuid:plan_id>/",
        payment_method_plan_detail,
        name="workspace-payment-method-plan-detail",
    ),
    path(
        "public/workspaces/<uuid:workspace_id>/",
        PublicWorkspacePaymentMethodView.as_view(),
        name="public-workspace-payment-methods",
    ),
    path(
        "stripe/connect/callback/",
        StripeConnectCallbackView.as_view(),
        name="workspace-payments-stripe-callback",
    ),
    path(
        "providers/health/",
        ProviderHealthController.as_view(),
        name="payment-provider-health",
    ),
]

# ── Billing URLs (mounted at /workspaces/<ws>/billing/ by workspace) ──

billing_urlpatterns = [
    path("overview/", WorkspaceBillingOverviewController.as_view(), name=WorkspaceBillingOverviewController.name),
    path("plans/", WorkspaceBillingPlansController.as_view(), name=WorkspaceBillingPlansController.name),
    path("history/", WorkspaceBillingHistoryController.as_view(), name=WorkspaceBillingHistoryController.name),
    path(
        "payment-methods/",
        WorkspacePaymentMethodListController.as_view(),
        name=WorkspacePaymentMethodListController.name,
    ),
    path(
        "payment-methods/setup-intent/",
        WorkspaceSetupIntentController.as_view(),
        name=WorkspaceSetupIntentController.name,
    ),
    path(
        "payment-methods/<str:pm_id>/default/",
        WorkspacePaymentMethodDefaultController.as_view(),
        name=WorkspacePaymentMethodDefaultController.name,
    ),
    path(
        "payment-methods/<str:pm_id>/",
        WorkspacePaymentMethodDetailController.as_view(),
        name=WorkspacePaymentMethodDetailController.name,
    ),
    path("plan/preview/", WorkspacePlanPreviewController.as_view(), name=WorkspacePlanPreviewController.name),
    path("plan/checkout/", WorkspacePlanCheckoutController.as_view(), name=WorkspacePlanCheckoutController.name),
    path("plan/cancel/", WorkspacePlanCancelController.as_view(), name=WorkspacePlanCancelController.name),
    path("plan/change/", WorkspacePlanChangeController.as_view(), name=WorkspacePlanChangeController.name),
    path("stripe/webhook/", StripeSubscriptionWebhookController.as_view(), name="workspace-billing-stripe-webhook"),
]

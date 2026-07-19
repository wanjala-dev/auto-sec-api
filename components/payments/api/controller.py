"""Unified billing controllers (CQRS pattern with write and read operations).

Handles both mutations and queries:
- Write operations: plan checkout, plan change, plan cancel, setup intents,
  payment method CRUD, webhook processing, shop checkout, and Stripe Connect
  callbacks.
- Read operations: billing overview, plans, history, payment methods, and
  provider information.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from components.payments.api.billing_support import (
    _append_query,
    _build_checkout_urls,
    _build_team_plan_checkout_request,
    _resolve_billing_plan,
    _resolve_frontend_url,
    _resolve_workspace_admin_request,
    logger,
)
from components.payments.application.service import (
    PaymentServicesFactory,
    TeamPlanBillingService,
    TeamPlanWebhookService,
    WorkspaceBillingService,
)
from components.payments.domain.errors import (
    PaymentConfigurationError,
    PaymentMethodNotFoundError,
    PaymentOnboardingConfigurationError,
    PaymentOnboardingError,
    SubscriptionError,
    UnsupportedPaymentProviderError,
)
from components.payments.mappers.rest.billing_v1_serializers import (
    billing_history_to_v1,
    billing_overview_to_v1,
    payment_plan_serializer_for_version,
    plan_preview_to_v1,
    public_payment_method_serializer_for_version,
    serialize_billing_plan_v1,
)
from components.payments.mappers.rest.payment_serializers import (
    PaymentPlanSerializer,
    PaymentProviderSerializer,
    WorkspacePaymentMethodSerializer,
    serialize_billing_plan,
)
from components.shared_kernel.serializers import EmptySerializer
from components.shared_kernel.utils.tenant_utils import hostname_from_request

# ── Service singletons ───────────────────────────────────────

_payment_services_factory = PaymentServicesFactory()
team_plan_billing_service: TeamPlanBillingService = _payment_services_factory.build_team_plan_billing_service()
team_plan_webhook_service: TeamPlanWebhookService = _payment_services_factory.build_team_plan_webhook_service()
workspace_billing_service: WorkspaceBillingService = _payment_services_factory.build_workspace_billing_service()
payment_method_service = _payment_services_factory.build_payment_method_service()


def _finalize_recipient_sponsorship_tier(method, plan) -> None:
    """Make a freshly-saved per-recipient sponsorship tier safe to charge.

    Applies to ``recipient_sponsorship`` plans scoped to a recipient only (the
    per-recipient amounts an admin sets on a donation form). Two guarantees the
    generic plan serializer doesn't make on its own:

    1. **Currency is the connected account's settlement currency**, never the
       client's input — a CAD account must charge CAD, or the form checkout 400s
       on a currency mismatch. The form-tier path sets this server-side; we do
       the same here rather than trusting the builder.
    2. **A recurring fixed-amount tier is provisioned a Stripe price** at save,
       so the form recurring checkout can ride its ``price_id`` (a form's own
       tiers provision at publish; per-recipient tiers have no publish step).
       One-time and custom-amount tiers need no price and are skipped.

    Best-effort provisioning: a failure is logged, never fatal to the save
    (mirrors the form-publish provisioning).
    """
    if getattr(plan, "context", None) != "recipient_sponsorship" or getattr(plan, "recipient_id", None) is None:
        return

    settlement = (getattr(method, "settlement_currency", None) or "usd").lower()
    if (getattr(plan, "currency", None) or "").lower() != settlement:
        plan.currency = settlement
        plan.save(update_fields=["currency", "updated_at"])

    if not getattr(plan, "is_recurring", False) or getattr(plan, "custom_amount", False):
        return
    provider_slug = getattr(getattr(method, "provider", None), "slug", None)
    if not provider_slug:
        return
    try:
        from components.payments.application.providers import (
            make_payment_gateway_provider,
        )

        gateway = make_payment_gateway_provider().get_gateway_for_provider(provider_slug)
        if gateway is not None:
            gateway.ensure_plan_resources(method, plan)
    except Exception:
        logger.exception(
            "recipient_sponsorship_tier_provision_failed plan_id=%s recipient_id=%s",
            getattr(plan, "id", None),
            getattr(plan, "recipient_id", None),
        )


# ── Write Operations ────────────────────────────────────────


class WorkspacePlanCheckoutController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-plan-checkout"
    serializer_class = EmptySerializer

    def post(self, request, *args, **kwargs):
        request._billing_site_domain = request.get_host()  # type: ignore[attr-defined]
        checkout_request = _build_team_plan_checkout_request(request)
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace

        plan = _resolve_billing_plan(checkout_request.plan_id) or _resolve_billing_plan(checkout_request.plan)
        if not plan:
            return Response({"error": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)

        # Delegate team and profile lookup to service layer
        team = None
        customer_email = None
        customer_name = None
        try:
            team, customer_email, customer_name = team_plan_billing_service.resolve_checkout_context(
                workspace=workspace,
                team_id=checkout_request.team_id,
                user_id=str(request.user.id),
            )
        except ValueError as exc:
            logger.warning("Checkout context resolution failed for workspace %s: %s", workspace.id, exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        success_url, cancel_url = _build_checkout_urls(
            checkout_request=checkout_request,
            plan=plan,
            team=team,
        )

        try:
            payload, status_code = team_plan_billing_service.checkout_team_plan(
                workspace=workspace,
                plan=plan,
                team=team,
                customer_email=customer_email,
                customer_name=customer_name,
                user_id=str(request.user.id),
                success_url=success_url,
                cancel_url=cancel_url,
                proration_behavior=checkout_request.proration_behavior,
            )
        except ValueError as exc:
            logger.warning("Plan checkout failed for workspace %s: %s", workspace.id, exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (SubscriptionError, PaymentConfigurationError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload, status=status_code)


class WorkspacePlanCancelController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-plan-cancel"
    serializer_class = EmptySerializer

    def post(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            plan = team_plan_billing_service.cancel_team_plan(workspace=workspace)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (SubscriptionError, PaymentConfigurationError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "status": "canceled",
                "plan": {"id": plan.id, "title": plan.title},
            },
            status=status.HTTP_200_OK,
        )


class WorkspacePlanChangeController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-plan-change"
    serializer_class = EmptySerializer

    def post(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace

        plan_value = (
            request.data.get("plan_id")
            or request.data.get("plan")
            or request.query_params.get("plan_id")
            or request.query_params.get("plan")
        )
        if not plan_value:
            return Response({"error": "plan_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        plan = _resolve_billing_plan(plan_value)
        if not plan:
            return Response({"error": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)

        proration_behavior = request.data.get("proration_behavior") or "create_prorations"
        try:
            subscription = team_plan_billing_service.apply_plan_change(
                workspace=workspace,
                plan=plan,
                proration_behavior=proration_behavior,
            )
        except ValueError as exc:
            logger.warning("Plan change failed for workspace %s: %s", workspace.id, exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (SubscriptionError, PaymentConfigurationError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "status": "updated",
                "subscription_id": (
                    subscription.get("id") if isinstance(subscription, dict) else getattr(subscription, "id", None)
                )
                if subscription
                else None,
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceSetupIntentController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-setup-intent"
    serializer_class = EmptySerializer

    def post(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            payload = workspace_billing_service.create_setup_intent(workspace=workspace)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except (PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_200_OK)


class WorkspacePaymentMethodDefaultController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-payment-method-default"
    serializer_class = EmptySerializer

    def post(self, request, pm_id: str, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            payload = workspace_billing_service.set_default_payment_method(
                workspace=workspace,
                payment_method_id=pm_id,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class WorkspacePaymentMethodDetailController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-payment-method-detail"
    serializer_class = EmptySerializer

    def delete(self, request, pm_id: str, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            payload = workspace_billing_service.detach_payment_method(
                workspace=workspace,
                payment_method_id=pm_id,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_200_OK)


@method_decorator(sensitive_post_parameters(), name="dispatch")
class StripeSubscriptionWebhookController(APIView):
    """Stripe subscription webhook receiver.

    ``sensitive_post_parameters()`` with no args marks every POST parameter
    sensitive for Django's exception reporter — webhook bodies carry Stripe
    signatures and customer PII that must not leak into error pages.
    """

    permission_classes = (permissions.AllowAny,)
    name = "stripe_webhook"
    serializer_class = EmptySerializer

    def get_throttles(self):
        from infrastructure.api.throttles import WebhookThrottle

        return [WebhookThrottle()]

    def post(self, request, *args, **kwargs):
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        transaction = _django_orm.transaction

        from components.payments.domain.errors import WebhookVerificationError

        logger.warning(
            "Deprecated billing webhook /team/stripe/webhook/ used. Use /workspaces/billing/stripe/webhook/."
        )
        with transaction.atomic():
            try:
                verification = _payment_services_factory.build_payment_runtime_provider().verify_webhook(
                    request,
                    endpoint_name="team_subscriptions",
                )
            except WebhookVerificationError as exc:
                # Signature mismatch is permanent — return 4xx so Stripe
                # stops retrying. The donation controller had the same bug
                # in Phase 1; this is the parallel fix for the team-plan
                # path. Returning 500 (the previous behaviour) made Stripe
                # retry forever on a misconfigured secret.
                return Response(
                    {"error": str(exc)},
                    status=getattr(exc, "status_code", 403),
                )
            except ValueError as exc:
                return HttpResponseBadRequest(str(exc))
            request.payment_api_key = verification.api_key  # type: ignore[attr-defined]
            request.payment_event = verification.payment_event  # type: ignore[attr-defined]
            request.payment_event_duplicate = verification.payment_event_duplicate  # type: ignore[attr-defined]
            request.payment_event_processable = verification.payment_event_processable  # type: ignore[attr-defined]
            event = verification.event
            method = verification.method
            workspace = verification.workspace
            provider = verification.provider_slug

            if provider != "stripe":
                return Response({"status": "ignored"})

            payment_event = getattr(request, "payment_event", None)
            should_process = getattr(request, "payment_event_processable", True)
            if payment_event and not should_process:
                return Response({"status": "duplicate"})

            try:
                team_plan_webhook_service.handle_verified_webhook(
                    event=event,
                    workspace=workspace,
                    method=method,
                    payment_event=payment_event,
                    api_key=getattr(request, "payment_api_key", None),
                )
            except ValueError as exc:
                return HttpResponseBadRequest(str(exc))
            return Response(status=200)


class WorkspacePaymentMethodViewSet(viewsets.ModelViewSet):
    serializer_class = WorkspacePaymentMethodSerializer
    lookup_field = "id"
    permission_classes = (permissions.IsAuthenticated,)

    def get_workspace(self) -> Workspace:
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        Workspace = _pkg_models.Workspace
        workspace_id = self.kwargs.get("workspace_id")
        workspace = get_object_or_404(Workspace, id=workspace_id)
        self._check_workspace_permissions(self.request, workspace)
        return workspace

    def _check_workspace_permissions(self, request, workspace: Workspace):
        # Canonical role check — mirror of the frontend's
        # canManageStoredWorkspacePermissions selector. The previous
        # implementation only allowed the literal workspace creator (or
        # Django staff), which locked out delegated admin personas even
        # though they have ``WorkspaceMembership.role='admin'``. Same bug
        # pattern as PaymentMathodsTab's old email-equality gate.
        from components.identity.application.providers.user_context_query_provider import (
            get_user_context_query_provider,
        )

        is_staff = getattr(request.user, "is_staff", False) or getattr(request.user, "is_admin", False)
        if is_staff:
            return

        role = (
            get_user_context_query_provider()
            .repository()
            .infer_workspace_role(
                user_id=request.user.id,
                workspace_id=workspace.id,
            )
        )
        if role in ("owner", "admin"):
            return

        raise PermissionDenied("You do not have permission to manage payment methods for this workspace.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            context["workspace"] = self.get_workspace()
        except Exception:
            pass
        return context

    def get_queryset(self):
        from django.db.models import Prefetch

        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        WorkspacePaymentMethod = _pkg_models.WorkspacePaymentMethod
        PaymentPlan = _pkg_models.PaymentPlan
        workspace = self.get_workspace()
        return (
            WorkspacePaymentMethod.objects.filter(workspace=workspace, is_deleted=False)
            .select_related("provider", "workspace", "tenant", "contribution_means")
            # ``WorkspacePaymentMethodSerializer.get_plans`` renders the active
            # plans per method row — prefetch the exact filtered/ordered set so
            # the serializer reads it without one plans-query per method.
            .prefetch_related(
                Prefetch(
                    "plans",
                    queryset=PaymentPlan.objects.filter(is_active=True).order_by("sort_order", "created_at"),
                    to_attr="prefetched_active_plans",
                )
            )
            .order_by("sort_order", "created_at")
        )

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs.get(self.lookup_field)
        obj = queryset.filter(**{self.lookup_field: lookup_value}).first()
        if not obj:
            workspace_id = self.kwargs.get("workspace_id")
            raise NotFound(
                detail={
                    "message": (
                        f"Payment method '{lookup_value}' was not found for workspace '{workspace_id}' "
                        "or it may have been removed."
                    ),
                    "hint": "Use GET /workspaces/payments/workspaces/<workspace_id>/methods/ to list the valid method IDs.",
                }
            )
        self.check_object_permissions(self.request, obj)
        return obj

    def check_object_permissions(self, request, obj):
        if request.method in permissions.SAFE_METHODS:
            return
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        WorkspacePaymentMethod = _pkg_models.WorkspacePaymentMethod

        workspace = obj.workspace if isinstance(obj, WorkspacePaymentMethod) else obj
        self._check_workspace_permissions(request, workspace)

    def perform_create(self, serializer):
        workspace = self.get_workspace()
        tenant = getattr(workspace, "tenant", None)
        user_id = self.request.user.id if self.request.user.is_authenticated else None
        method = serializer.save(
            workspace=workspace,
            tenant=tenant,
            created_by=self.request.user if self.request.user.is_authenticated else None,
            updated_by=self.request.user if self.request.user.is_authenticated else None,
        )
        # Delegate credential encryption to service layer
        credentials = getattr(method, "_pending_credentials", None)
        if credentials is not None:
            payment_method_service.encrypt_and_save_payment_method_credentials(
                method_id=method.id,
                credentials=credentials,
                updated_by_id=user_id,
            )

    def perform_update(self, serializer):
        user_id = self.request.user.id if self.request.user.is_authenticated else None
        method = serializer.save(updated_by=self.request.user if self.request.user.is_authenticated else None)
        # Delegate credential encryption to service layer
        credentials = getattr(method, "_pending_credentials", None)
        if credentials is not None:
            payment_method_service.encrypt_and_save_payment_method_credentials(
                method_id=method.id,
                credentials=credentials,
                updated_by_id=user_id,
            )

    @action(detail=True, methods=["post"], url_path="set-primary")
    def set_primary(self, request, workspace_id: str, id: str = None, **kwargs):
        method = self.get_object()
        try:
            payment_method_service.set_primary_payment_method(
                method_id=method.id,
                updated_by_id=request.user.id if request.user.is_authenticated else None,
            )
        except PaymentMethodNotFoundError as exc:
            raise NotFound(detail=str(exc)) from exc
        return Response({"status": "ok"})

    @action(detail=True, methods=["post"], url_path="authorize")
    def authorize(self, request, workspace_id: str, id: str = None, **kwargs):
        method = self.get_object()
        payload_redirect = _resolve_frontend_url(request, request.data.get("redirect_url"))
        refresh_override = request.data.get("refresh_url")
        refresh_redirect = _resolve_frontend_url(request, refresh_override or payload_redirect)
        state = secrets.token_urlsafe(24)

        callback_base = request.build_absolute_uri(reverse("workspace-payments-stripe-callback"))
        callback_params = {
            "method_id": str(method.id),
            "workspace_id": str(method.workspace_id),
            "state": state,
        }

        try:
            result = payment_method_service.start_payment_method_onboarding(
                method_id=method.id,
                state=state,
                post_onboard_redirect=payload_redirect,
                post_onboard_refresh=refresh_redirect,
                callback_success_url=_append_query(
                    callback_base,
                    {**callback_params, "result": "success"},
                ),
                callback_refresh_url=_append_query(
                    callback_base,
                    {**callback_params, "result": "refresh"},
                ),
                updated_by_id=request.user.id if request.user.is_authenticated else None,
            )
        except UnsupportedPaymentProviderError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PaymentOnboardingConfigurationError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except PaymentOnboardingError as exc:
            message = (
                "Failed to create Stripe account."
                if exc.stage == "account_creation"
                else "Failed to initiate Stripe onboarding."
            )
            return Response(
                {"error": message, "details": exc.details},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except PaymentMethodNotFoundError as exc:
            raise NotFound(detail=str(exc)) from exc

        return Response(
            {
                "redirect_url": result.redirect_url,
                "state": result.state,
                "account_id": result.account_id,
                "expires_at": result.expires_at,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="test-connection")
    def test_connection(self, request, workspace_id: str, id: str = None, **kwargs):
        """Probe the live provider with the stored credentials.

        Stripe: ``stripe.Account.retrieve(account_id)`` and check
        ``charges_enabled``. Returns red/green for the Settings UI so the
        operator finds out *now* whether the saved keys actually work,
        instead of when the first donor lands on Checkout.
        """
        method = self.get_object()
        provider_slug = (method.provider.slug or "").lower()

        if provider_slug == "stripe":
            from components.payments.application.providers.encryption_provider import (
                get_encryption_provider,
            )
            from components.payments.application.providers.payment_gateway_provider import (
                make_payment_gateway_provider,
            )
            from components.payments.application.providers.payment_method_credentials_provider import (
                get_payment_method_credentials_provider,
            )

            PaymentCredentialDecryptionError = get_encryption_provider().decryption_error
            read_payment_method_credentials = get_payment_method_credentials_provider().read_payment_method_credentials

            try:
                credentials = read_payment_method_credentials(method)
            except PaymentCredentialDecryptionError as exc:
                return Response(
                    {"ok": False, "error": str(exc)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
            account_id = method.provider_account_id or credentials.get("account_id")
            if not api_key:
                return Response(
                    {"ok": False, "error": "No Stripe secret key configured."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            gateway = make_payment_gateway_provider().get_gateway_for_provider("stripe")
            result = gateway.verify_account(api_key=api_key, account_id=account_id)

            method.last_tested_at = timezone.now()
            method.save(update_fields=["last_tested_at", "updated_at"])

            if not result.get("ok"):
                err = result.get("error", "Stripe verification failed.")
                if "authentication" in err.lower() or "api key" in err.lower():
                    return Response(
                        {"ok": False, "error": "Invalid Stripe API key.", "details": err},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
                return Response({"ok": False, "error": err}, status=status.HTTP_502_BAD_GATEWAY)

            return Response(
                {"ok": True, "provider": "stripe", **result},
                status=status.HTTP_200_OK,
            )

        if provider_slug == "braintree":
            return Response(
                {
                    "ok": False,
                    "error": (
                        "Braintree is gated behind the payments.braintree feature "
                        "flag. Connection-test will be implemented when the "
                        "marketplace onboarding flow ships."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {"ok": False, "error": f"Connection test not supported for {provider_slug}."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["post"], url_path="webhooks")
    def upsert_webhook(self, request, workspace_id: str, id: str = None, **kwargs):
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        PaymentWebhookEndpoint = _pkg_models.PaymentWebhookEndpoint
        method = self.get_object()
        name = (request.data.get("name") or "default").strip()
        url = (request.data.get("url") or "").strip()
        status_value = request.data.get("status") or PaymentWebhookEndpoint.STATUS_ACTIVE

        if not url:
            return Response({"error": "Webhook URL is required."}, status=status.HTTP_400_BAD_REQUEST)
        if status_value not in dict(PaymentWebhookEndpoint.STATUS_CHOICES):
            return Response({"error": "Invalid webhook status."}, status=status.HTTP_400_BAD_REQUEST)

        secret = (request.data.get("signing_secret") or request.data.get("secret") or "").strip()
        provider_endpoint_id = (request.data.get("provider_endpoint_id") or "").strip()
        auto_register = bool(request.data.get("auto_register"))
        existing_endpoint = PaymentWebhookEndpoint.objects.filter(method=method, name=name).first()
        if method.provider.slug == "stripe":
            # Auto-register: call Stripe to create the endpoint and capture
            # the secret programmatically. Removes the operator footgun of
            # pasting secrets manually (and pasting the wrong one). Also
            # guarantees the endpoint configuration on Stripe's side matches
            # what we expect.
            if auto_register and not secret:
                # Stripe delivers every event on a URL to every endpoint
                # registered for it, each signed with that endpoint's own
                # secret. One endpoint per (url, name, connect-mode) is the
                # correct cardinality — a second one just double-delivers
                # and, once its secret drifts out of the DB, 403s every
                # delivery until Stripe disables it (2026-07-04 incident).
                # Reuse a sibling method's registration when one exists.
                is_connect = bool(method.provider_account_id)
                reusable = (
                    PaymentWebhookEndpoint.objects.filter(
                        url=url,
                        name=name,
                        status=PaymentWebhookEndpoint.STATUS_ACTIVE,
                        method__provider=method.provider,
                    )
                    .exclude(provider_endpoint_id="")
                    .exclude(signing_secret="")
                    .exclude(method=method)
                )
                if is_connect:
                    reusable = reusable.exclude(method__provider_account_id="")
                else:
                    reusable = reusable.filter(method__provider_account_id="")
                reusable = reusable.first()
                if reusable is not None:
                    secret = reusable.signing_secret
                    provider_endpoint_id = reusable.provider_endpoint_id
            if auto_register and not secret:
                from components.payments.application.providers.encryption_provider import (
                    get_encryption_provider,
                )
                from components.payments.application.providers.payment_gateway_provider import (
                    make_payment_gateway_provider,
                )
                from components.payments.application.providers.payment_method_credentials_provider import (
                    get_payment_method_credentials_provider,
                )

                PaymentCredentialDecryptionError = get_encryption_provider().decryption_error
                read_payment_method_credentials = (
                    get_payment_method_credentials_provider().read_payment_method_credentials
                )

                try:
                    credentials = read_payment_method_credentials(method)
                except PaymentCredentialDecryptionError as exc:
                    return Response(
                        {"error": str(exc)},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                api_key = credentials.get("secret_key") or getattr(settings, "STRIPE_SECRET_KEY", None)
                if not api_key:
                    return Response(
                        {"error": "No Stripe secret key configured for this method."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                gateway = make_payment_gateway_provider().get_gateway_for_provider("stripe")
                result = gateway.register_webhook_endpoint(
                    url=url,
                    enabled_events=[
                        "checkout.session.completed",
                        "checkout.session.expired",
                        "invoice.payment_succeeded",
                        "invoice.payment_failed",
                        "customer.subscription.created",
                        "customer.subscription.updated",
                        "customer.subscription.paused",
                        "customer.subscription.resumed",
                        "customer.subscription.deleted",
                        "payment_intent.payment_failed",
                        "charge.refunded",
                        "charge.dispute.created",
                        "charge.dispute.closed",
                        "charge.dispute.funds_withdrawn",
                        "charge.dispute.funds_reinstated",
                    ],
                    api_key=api_key,
                    description=f"Auto-registered for workspace {method.workspace_id}",
                    connect=bool(method.provider_account_id),
                )
                if result.get("error"):
                    return Response(
                        {"error": "Failed to register webhook endpoint.", "details": result["error"]},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                secret = result.get("secret") or ""
                provider_endpoint_id = result.get("id") or ""
                if not secret:
                    return Response(
                        {"error": "Provider did not return a signing secret."},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

            if not secret:
                if existing_endpoint and existing_endpoint.signing_secret:
                    secret = existing_endpoint.signing_secret
                    provider_endpoint_id = provider_endpoint_id or existing_endpoint.provider_endpoint_id
                else:
                    secret = getattr(settings, "STRIPE_WEBHOOK_KEY", "") or getattr(
                        settings,
                        "STRIPE_CONNECT_WEBHOOK_SECRET",
                        "",
                    )
            if not secret:
                return Response(
                    {
                        "error": (
                            "Stripe webhook signing_secret is required. Pass "
                            "`auto_register: true` to have the backend create "
                            "the endpoint via the Stripe API and capture the "
                            "secret automatically."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif not secret:
            secret = secrets.token_urlsafe(32)
        endpoint, created = PaymentWebhookEndpoint.objects.update_or_create(
            method=method,
            name=name,
            defaults={
                "url": url,
                "signing_secret": secret,
                "provider_endpoint_id": provider_endpoint_id,
                "status": status_value,
                "last_error": "",
            },
        )

        return Response(
            {
                "id": endpoint.id,
                "name": endpoint.name,
                "url": endpoint.url,
                "status": endpoint.status,
                "has_signing_secret": bool(endpoint.signing_secret),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="plans")
    def manage_plans(self, request, workspace_id: str, id: str = None, **kwargs):
        # ``**kwargs`` absorbs the ``/api/vN/`` ``version`` URL kwarg so the
        # versioned mount routes to this action. The READ (GET) path
        # version-selects ``PaymentPlanSerializer`` -> v1 money objects; the
        # write (POST) path below keeps the v0 serializer byte-identical.
        method = self.get_object()
        context_key = request.query_params.get("context")
        recipient_id = request.query_params.get("recipient_id") or request.query_params.get("recipient_id")

        if request.method.lower() == "get":
            plans_qs = method.plans.filter(is_active=True)
            if context_key:
                plans_qs = plans_qs.filter(context=context_key)
            if recipient_id:
                recipient_plans = plans_qs.filter(recipient_id=recipient_id)
                plans_qs = recipient_plans if recipient_plans.exists() else plans_qs.filter(recipient__isnull=True)
            read_serializer_cls = payment_plan_serializer_for_version(getattr(request, "version", None))
            serializer = read_serializer_cls(
                plans_qs.order_by("sort_order", "created_at"),
                many=True,
                context={"method": method},
            )
            return Response(serializer.data)

        serializer = PaymentPlanSerializer(
            data=request.data,
            context={"method": method},
        )
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        _finalize_recipient_sponsorship_tier(method, plan)
        return Response(
            PaymentPlanSerializer(plan, context={"method": method}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["patch", "delete"], url_path=r"plans/(?P<plan_id>[0-9a-f\-]{36})")
    def manage_plan_detail(self, request, workspace_id: str, plan_id: str, id: str = None, **kwargs):
        method = self.get_object()
        plan = method.plans.filter(id=plan_id).first()
        if not plan:
            return Response({"error": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.method.lower() == "delete":
            plan.is_active = False
            plan.save(update_fields=["is_active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = PaymentPlanSerializer(
            plan,
            data=request.data,
            partial=True,
            context={"method": method},
        )
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        _finalize_recipient_sponsorship_tier(method, plan)
        return Response(PaymentPlanSerializer(plan, context={"method": method}).data)

    def perform_destroy(self, instance):
        payment_method_service.delete_payment_method(
            method_id=instance.id,
            updated_by_id=self.request.user.id if self.request.user.is_authenticated else None,
        )


class StripeConnectCallbackView(APIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = EmptySerializer

    def get(self, request):
        method_id = request.query_params.get("method_id")
        state = request.query_params.get("state")
        result = request.query_params.get("result", "success")
        error_code = request.query_params.get("error")
        error_description = request.query_params.get("error_description")
        account_hint = request.query_params.get("account") or request.query_params.get("account_id")

        if not method_id:
            return Response({"error": "Missing payment method."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = payment_method_service.complete_payment_method_onboarding(
                method_id=method_id,
                state=state,
                result=result,
                error_code=error_code,
                error_description=error_description,
                account_hint=account_hint,
            )
        except PaymentMethodNotFoundError as exc:
            raise NotFound(detail=str(exc)) from exc
        return self._redirect(
            request,
            outcome.redirect_target,
            status_code=outcome.status_code,
            extra_params=outcome.extra_params,
        )

    def _redirect(self, request, target: str, status_code: str, extra_params: dict | None = None):
        params = {"payment_onboarding": status_code}
        if extra_params:
            params.update(extra_params)
        url = _append_query(_resolve_frontend_url(request, target), params)
        return HttpResponseRedirect(url)


# ── Read Operations ────────────────────────────────────────


class WorkspacePlanPreviewController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-plan-preview"
    serializer_class = EmptySerializer

    def get(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace

        plan_value = request.query_params.get("plan_id") or request.query_params.get("plan")
        if not plan_value:
            return Response({"error": "plan_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        plan = _resolve_billing_plan(plan_value)
        if not plan:
            return Response({"error": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)

        if not workspace.stripe_subscription_id:
            return Response(
                {"error": "No active subscription to preview."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            invoice = team_plan_billing_service.preview_plan_change(
                workspace=workspace,
                plan=plan,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (SubscriptionError, PaymentConfigurationError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        if not invoice:
            return Response(
                {"error": "Unable to preview plan change."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        preview_payload = {
            "amount_due": invoice.get("amount_due"),
            "currency": invoice.get("currency"),
            "next_payment_attempt": invoice.get("next_payment_attempt"),
            "lines": invoice.get("lines", {}).get("data", []),
        }
        # v1 reshapes the Stripe MINOR-unit ``amount_due`` into a C1 money object
        # and normalizes the Stripe-epoch ``next_payment_attempt`` to ISO-Z.
        # ``lines`` is Stripe's raw invoice-line payload — left untouched.
        if getattr(request, "version", None) == "v1":
            preview_payload = plan_preview_to_v1(preview_payload)
        return Response(preview_payload, status=status.HTTP_200_OK)


class WorkspaceBillingOverviewController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-overview"
    serializer_class = EmptySerializer

    def get(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            overview = workspace_billing_service.get_overview(workspace=workspace)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except (PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        subscription = overview["subscription"]

        plan = workspace.plan
        plan_payload = None
        if plan:
            plan_payload = {
                "id": plan.id,
                "title": plan.title,
                "price": plan.price,
                "currency": plan.currency,
                "billing_interval": plan.billing_interval,
                "interval_count": plan.interval_count,
            }

        overview_payload = {
            "workspace_id": str(workspace.id),
            "plan": plan_payload,
            "plan_status": workspace.plan_status,
            "plan_end_date": workspace.plan_end_date,
            "stripe_customer_id": workspace.stripe_customer_id,
            "stripe_subscription_id": workspace.stripe_subscription_id,
            "subscription_status": subscription.get("status") if subscription else None,
            "current_period_end": subscription.get("current_period_end") if subscription else None,
            "default_payment_method_id": overview["default_payment_method_id"],
            "payment_methods": overview["payment_methods"],
            "upcoming_invoice": overview["upcoming_invoice"],
        }
        # v1: ``plan.price`` (major) + ``upcoming_invoice.amount_due`` (Stripe
        # minor) -> C1 money objects; ``plan_end_date`` (datetime) +
        # ``current_period_end`` (Stripe epoch) -> ISO-Z.
        if getattr(request, "version", None) == "v1":
            overview_payload = billing_overview_to_v1(overview_payload, workspace=workspace)
        return Response(overview_payload, status=status.HTTP_200_OK)


class WorkspaceBillingPlansController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-plans"
    serializer_class = EmptySerializer

    def get(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        from components.team.application.providers.team_models_provider import (
            get_team_models_provider,
        )

        _pkg_models = get_team_models_provider()
        Plan = _pkg_models.Plan
        plans = Plan.objects.all()
        # v1 wraps each plan's MAJOR-unit ``price`` in a C1 money object; v0
        # keeps the bare integer price. Entitlement/limit keys are unchanged.
        if getattr(request, "version", None) == "v1":
            plan_rows = [serialize_billing_plan_v1(serialize_billing_plan(plan)) for plan in plans]
        else:
            plan_rows = [serialize_billing_plan(plan) for plan in plans]
        return Response(
            {
                "workspace_id": str(workspace.id),
                "plans": plan_rows,
            },
            status=status.HTTP_200_OK,
        )


class WorkspaceBillingHistoryController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-history"
    serializer_class = EmptySerializer

    def get(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        limit_raw = request.query_params.get("limit")
        starting_after = request.query_params.get("starting_after")
        ending_before = request.query_params.get("ending_before")
        try:
            limit = int(limit_raw) if limit_raw else 10
        except (TypeError, ValueError):
            return Response(
                {"error": "limit must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = max(1, min(limit, 50))

        try:
            history = workspace_billing_service.get_history(
                workspace=workspace,
                limit=limit,
                starting_after=starting_after,
                ending_before=ending_before,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except (PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        context = history["context"]

        history_payload = {
            "workspace_id": str(workspace.id),
            "subscription_id": context.subscription_id,
            "invoices": history["invoices"],
            "has_more": history["has_more"],
            "next_cursor": history["next_cursor"],
        }
        # v1 reshapes each invoice row's Stripe MINOR-unit amounts (due/paid/
        # remaining) into C1 money objects and normalizes the Stripe-epoch
        # created/period_start/period_end timestamps to ISO-Z.
        if getattr(request, "version", None) == "v1":
            history_payload = billing_history_to_v1(history_payload)
        return Response(history_payload, status=status.HTTP_200_OK)


class WorkspacePaymentMethodListController(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    name = "billing-payment-methods"
    serializer_class = EmptySerializer

    def get(self, request, *args, **kwargs):
        workspace = _resolve_workspace_admin_request(request)
        if isinstance(workspace, Response):
            return workspace
        try:
            payment_methods = workspace_billing_service.list_payment_methods(workspace=workspace)
        except (ValueError, PaymentConfigurationError, SubscriptionError) as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payment_methods, status=status.HTTP_200_OK)


class PaymentProviderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentProviderSerializer
    permission_classes = (permissions.AllowAny,)

    def get_queryset(self):
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        PaymentProvider = _pkg_models.PaymentProvider
        qs = PaymentProvider.objects.filter(is_active=True)
        if not self.request.user.is_authenticated:
            qs = qs.exclude(provider_type=PaymentProvider.API, is_active=False)
        return qs.order_by("display_name")


class PublicWorkspacePaymentMethodView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get_workspace(self, workspace_id: str, request):
        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        Workspace = _pkg_models.Workspace
        workspace = get_object_or_404(Workspace, id=workspace_id)
        hostname = hostname_from_request(request)
        if hostname and not getattr(request, "tenant", None):
            request.tenant = hostname  # type: ignore[attr-defined]
        return workspace

    def get(self, request, workspace_id: str, **kwargs):
        # ``**kwargs`` absorbs the ``/api/vN/`` ``version`` URL kwarg. v1
        # re-renders each nested plan's MAJOR-unit ``amount`` as a C1 money
        # object (via the version-selected serializer); the method row itself
        # carries no money, so it is otherwise byte-identical to v0.
        from components.shared_kernel.application.providers.django_orm_provider import (
            get_django_orm_provider as _get_django_orm_provider,
        )

        _django_orm = _get_django_orm_provider()
        Q = _django_orm.Q
        Prefetch = _django_orm.Prefetch

        from components.workspace.application.providers.workspaces_models_provider import (
            get_workspaces_models_provider,
        )

        _pkg_models = get_workspaces_models_provider()
        PaymentProvider = _pkg_models.PaymentProvider
        WorkspacePaymentMethod = _pkg_models.WorkspacePaymentMethod
        PaymentPlan = _pkg_models.PaymentPlan
        workspace = self.get_workspace(workspace_id, request)
        context = request.query_params.get("context", "donations")
        recipient_id = request.query_params.get("recipient_id")
        methods = (
            WorkspacePaymentMethod.objects.filter(
                workspace=workspace,
                status=WorkspacePaymentMethod.STATUS_ACTIVE,
                is_deleted=False,
            )
            .filter(
                Q(provider__provider_type=PaymentProvider.API)
                | Q(
                    provider__provider_type=PaymentProvider.MANUAL,
                    allow_public_listing=True,
                )
            )
            .filter(Q(enabled_contexts__contains=[context]) | Q(enabled_contexts=[]))
            .select_related("provider")
            # ``PublicPaymentMethodSerializer.get_plans`` renders the
            # context-scoped active plans per method row — prefetch that exact
            # set so the public listing endpoint reads it in-memory instead of
            # firing plans + exists + re-filter queries per method.
            .prefetch_related(
                Prefetch(
                    "plans",
                    queryset=PaymentPlan.objects.filter(context=context, is_active=True).order_by(
                        "sort_order", "created_at"
                    ),
                    to_attr="prefetched_context_plans",
                )
            )
            .order_by("sort_order", "created_at")
        )
        serializer_cls = public_payment_method_serializer_for_version(getattr(request, "version", None))
        serializer = serializer_cls(
            methods,
            many=True,
            context={"plan_filters": {"context": context, "recipient_id": recipient_id}},
        )
        return Response(serializer.data)


__all__ = [
    # Write Operations
    "StripeConnectCallbackView",
    "StripeSubscriptionWebhookController",
    "WorkspacePaymentMethodDefaultController",
    "WorkspacePaymentMethodDetailController",
    "WorkspacePaymentMethodViewSet",
    "WorkspacePlanCancelController",
    "WorkspacePlanChangeController",
    "WorkspacePlanCheckoutController",
    "WorkspaceSetupIntentController",
    # Read Operations
    "PaymentProviderViewSet",
    "PublicWorkspacePaymentMethodView",
    "WorkspaceBillingHistoryController",
    "WorkspaceBillingOverviewController",
    "WorkspaceBillingPlansController",
    "WorkspacePaymentMethodListController",
    "WorkspacePlanPreviewController",
    # Health / Ops
    "ProviderHealthController",
]


class ProviderHealthController(APIView):
    """Admin-only endpoint that exposes circuit-breaker health for all
    registered payment providers.

    GET /payments/providers/health/
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        from components.payments.application.providers.payment_gateway_provider import (
            PaymentGatewayProvider,
        )

        provider = PaymentGatewayProvider()
        snapshots = provider.provider_health()
        data = [
            {
                "provider": s.slug,
                "state": s.state.value,
                "failure_count": s.failure_count,
                "success_count": s.success_count,
                "failure_rate": round(s.failure_rate, 4),
            }
            for s in snapshots
        ]
        return Response(data)

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from components.payments.application.providers import make_payment_gateway_provider
from components.payments.domain.errors import UnsupportedPaymentProviderError
from components.payments.infrastructure.adapters.payment_method_credentials import (
    payment_method_has_credentials,
)
from components.subscription.domain.entitlements import (
    EntitlementKey,
    EntitlementsResolver,
)
from infrastructure.persistence.workspaces.payments.models import (
    PaymentPlan,
    PaymentProvider,
    PaymentWebhookEndpoint,
    WorkspacePaymentMethod,
)


def _get_payment_gateway(provider_slug: str | None):
    if not provider_slug:
        return None
    try:
        return make_payment_gateway_provider().get_gateway_for_provider(provider_slug)
    except UnsupportedPaymentProviderError:
        return None


def _get_gateway_for_method(method: WorkspacePaymentMethod):
    return _get_payment_gateway(method.provider.slug)


class PaymentMethodStatusField(serializers.ChoiceField):
    """Allow legacy status aliases while still persisting canonical values."""

    def to_internal_value(self, data):
        if isinstance(data, str) and data.lower() == "inactive":
            data = WorkspacePaymentMethod.STATUS_DISABLED
        return super().to_internal_value(data)


class PaymentProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentProvider
        fields = (
            "id",
            "slug",
            "display_name",
            "provider_type",
            "description",
            "icon",
            "docs_url",
            "capabilities",
            "config_template",
            "oauth_settings",
            "is_active",
        )


class PaymentWebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentWebhookEndpoint
        fields = (
            "id",
            "name",
            "url",
            "signing_secret",
            "status",
            "last_error",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")
        extra_kwargs = {"signing_secret": {"write_only": True}}


class WorkspacePaymentMethodSerializer(serializers.ModelSerializer):
    provider = serializers.SlugRelatedField(slug_field="slug", queryset=PaymentProvider.objects.filter(is_active=True))
    status = PaymentMethodStatusField(
        choices=WorkspacePaymentMethod.STATUS_CHOICES,
        default=WorkspacePaymentMethod.STATUS_DRAFT,
        required=False,
    )
    # Stripe Connect (and other auto-onboarded providers) don't have a
    # ``provider_account_id`` until onboarding completes. The model field
    # is ``blank=True`` but DRF auto-generates ``required=True`` because
    # there's no default — override here so a new draft method can be
    # created with an empty account id.
    provider_account_id = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    primary_contexts = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
    )
    credentials = serializers.DictField(
        required=False,
        write_only=True,
        help_text="Provider credentials or OAuth tokens; never returned in responses.",
    )
    webhooks = PaymentWebhookSerializer(many=True, read_only=True)
    plans = serializers.SerializerMethodField()

    class Meta:
        model = WorkspacePaymentMethod
        fields = (
            "id",
            "workspace",
            "tenant",
            "provider",
            "display_name",
            "status",
            "is_primary",
            "sort_order",
            "enabled_contexts",
            "provider_account_id",
            "public_instructions",
            "metadata",
            "last_error",
            "is_deleted",
            "deleted_at",
            "contribution_means",
            "primary_contexts",
            "allow_public_listing",
            "created_at",
            "updated_at",
            "credentials",
            "credentials_updated_at",
            "last_tested_at",
            "last_error_at",
            "webhooks",
            "plans",
        )
        read_only_fields = (
            "created_at",
            "updated_at",
            "workspace",
            "tenant",
            "is_deleted",
            "deleted_at",
            "credentials_updated_at",
            "last_tested_at",
            "last_error_at",
        )

    def validate_enabled_contexts(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("enabled_contexts must be a list.")
        return value

    def validate_primary_contexts(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("primary_contexts must be a list.")
        return value

    def validate_credentials(self, value: dict[str, Any]):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError("credentials must be an object.")

        provider = self.initial_data.get("provider") or getattr(self.instance, "provider", None)
        provider_slug = provider.slug if isinstance(provider, PaymentProvider) else provider
        required_fields = {
            "stripe": ["secret_key"],
            "bitpay": ["token"],
            "braintree": ["merchant_id", "public_key", "private_key"],
        }
        # Allow provider-specific slugs with suffixes (e.g., "stripe-us") to reuse base schemas.
        slug_candidates = [
            provider_slug,
            provider_slug.split("-")[0] if isinstance(provider_slug, str) and "-" in provider_slug else provider_slug,
            provider_slug.split("_")[0] if isinstance(provider_slug, str) and "_" in provider_slug else provider_slug,
        ]
        required_keys = next(
            (required_fields[slug] for slug in slug_candidates if slug in required_fields),
            [],
        )
        missing = [key for key in required_keys if not value.get(key)]
        if missing:
            raise serializers.ValidationError(
                f"Missing required credential field(s) for {provider_slug}: {', '.join(missing)}"
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        provider = attrs.get("provider") or getattr(self.instance, "provider", None)
        status_value = attrs.get("status", getattr(self.instance, "status", WorkspacePaymentMethod.STATUS_DRAFT))
        credentials = attrs.get("credentials")
        enabled_contexts = attrs.get("enabled_contexts", getattr(self.instance, "enabled_contexts", [])) or []
        primary_contexts = attrs.get("primary_contexts", getattr(self.instance, "primary_contexts", [])) or []
        allow_public_listing = attrs.get(
            "allow_public_listing",
            getattr(self.instance, "allow_public_listing", False),
        )

        provider_slug = provider.slug if isinstance(provider, PaymentProvider) else provider
        base_provider_slug = None
        if isinstance(provider_slug, str):
            base_provider_slug = provider_slug.split("-")[0].split("_")[0]
        else:
            base_provider_slug = provider_slug

        if provider and getattr(provider, "provider_type", None) == PaymentProvider.API:
            requires_creds = status_value in (
                WorkspacePaymentMethod.STATUS_PENDING,
                WorkspacePaymentMethod.STATUS_ACTIVE,
                WorkspacePaymentMethod.STATUS_REQUIRES_ACTION,
            )
            has_existing_creds = payment_method_has_credentials(self.instance) if self.instance else False
            if requires_creds and not (credentials or has_existing_creds):
                platform_stripe_key = getattr(settings, "STRIPE_SECRET_KEY", "")
                allow_platform_stripe = base_provider_slug == "stripe" and platform_stripe_key
                if not allow_platform_stripe:
                    raise serializers.ValidationError(
                        {"credentials": "Credentials are required to activate or authorize this payment method."}
                    )
            if not _get_payment_gateway(base_provider_slug):
                raise serializers.ValidationError(
                    {"provider": f"No adapter is configured for provider '{provider.slug}'."}
                )

        is_primary = attrs.get("is_primary", getattr(self.instance, "is_primary", False))
        workspace = attrs.get("workspace") or self.context.get("workspace") or getattr(self.instance, "workspace", None)
        provider_for_query = provider
        if is_primary and workspace and provider_for_query:
            conflict = (
                WorkspacePaymentMethod.objects.filter(
                    workspace=workspace, provider=provider_for_query, is_primary=True, is_deleted=False
                )
                .exclude(id=getattr(self.instance, "id", None))
                .exists()
            )
            if conflict:
                raise serializers.ValidationError(
                    {"is_primary": "Another primary payment method already exists for this provider and workspace."}
                )

        invalid_primary_contexts = [ctx for ctx in primary_contexts if ctx not in enabled_contexts]
        if invalid_primary_contexts:
            raise serializers.ValidationError(
                {
                    "primary_contexts": f"Primary contexts must be a subset of enabled_contexts: {', '.join(invalid_primary_contexts)}"
                }
            )
        if allow_public_listing and provider and provider.provider_type != PaymentProvider.MANUAL:
            raise serializers.ValidationError(
                {"allow_public_listing": "Public listing toggle applies to manual/offline payment methods only."}
            )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> WorkspacePaymentMethod:
        # Credentials are removed but NOT encrypted here.
        # Credential encryption is now delegated to the service layer.
        credentials = validated_data.pop("credentials", None)
        method = super().create(validated_data)
        # Store credentials on instance for controller/service to handle encryption
        if credentials is not None:
            method._pending_credentials = credentials  # type: ignore[attr-defined]
        return method

    def update(self, instance: WorkspacePaymentMethod, validated_data: dict[str, Any]) -> WorkspacePaymentMethod:
        # Credentials are removed but NOT encrypted here.
        # Credential encryption is now delegated to the service layer.
        credentials = validated_data.pop("credentials", None)
        last_error = validated_data.get("last_error")
        method = super().update(instance, validated_data)
        if credentials is not None:
            method._pending_credentials = credentials  # type: ignore[attr-defined]
        if last_error is not None:
            method.last_error_at = timezone.now() if last_error else None
            method.save(update_fields=["last_error", "last_error_at", "updated_at"])
        return method

    def get_plans(self, obj: WorkspacePaymentMethod):
        # List/detail reads come through the viewset queryset, which prefetches
        # the active plans (with their recipients) into ``prefetched_active_plans``
        # — reading it here keeps the method-list endpoint at a constant query
        # count. The query fallback exists ONLY for write-path responses
        # (create/update serialize a freshly-saved instance that never went
        # through ``get_queryset``); it mirrors the prefetch exactly.
        plans = getattr(obj, "prefetched_active_plans", None)
        if plans is None:
            plans = obj.plans.filter(is_active=True).order_by("sort_order", "created_at")
        return PaymentPlanSerializer(plans, many=True, context={"method": obj}).data


class PaymentPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentPlan
        fields = (
            "id",
            "context",
            "slug",
            "label",
            "amount",
            "currency",
            "interval",
            "interval_count",
            "is_recurring",
            "custom_amount",
            "sort_order",
            "is_active",
            "product_id",
            "price_id",
        )
        read_only_fields = ("id", "product_id", "price_id")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        method: WorkspacePaymentMethod = self.context["method"]

        # A plan must not attach to a half-onboarded Connect method. A
        # `result=success` OAuth callback can still leave the account
        # Restricted (`charges_enabled=False`), persisted as
        # status=requires_action / pending. Creating a plan on it lets
        # checkouts succeed at Stripe while funds freeze and the webhook
        # router can't resolve the event. Creation-only (an existing plan's
        # method is already onboarded; an update mustn't be blocked if the
        # method later needs re-verification). This gate was dropped in the
        # DDD/Hex refactor (790adb07) and is restored here.
        if self.instance is None and getattr(method, "status", None) in (
            WorkspacePaymentMethod.STATUS_REQUIRES_ACTION,
            WorkspacePaymentMethod.STATUS_PENDING,
        ):
            raise serializers.ValidationError(
                {
                    "method": (
                        "This payment method has not finished Stripe Connect "
                        "onboarding. Complete onboarding before creating plans."
                    )
                }
            )

        interval = attrs.get("interval", getattr(self.instance, "interval", None))
        is_recurring = attrs.get(
            "is_recurring",
            getattr(self.instance, "is_recurring", True),
        )
        if is_recurring and not interval:
            raise serializers.ValidationError({"interval": "Recurring plans must define an interval."})

        interval_count = attrs.get(
            "interval_count",
            getattr(self.instance, "interval_count", 1),
        )
        if is_recurring and (interval_count is None or interval_count < 1):
            raise serializers.ValidationError({"interval_count": "Interval count must be at least 1."})
        if not is_recurring and interval_count not in (None, 1):
            raise serializers.ValidationError({"interval_count": "Non-recurring plans must use interval_count=1."})

        custom_amount = attrs.get(
            "custom_amount",
            getattr(self.instance, "custom_amount", False),
        )
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
        if not custom_amount and (amount is None or amount <= 0):
            raise serializers.ValidationError({"amount": "Amount must be greater than zero."})

        slug = attrs.get("slug")
        label = attrs.get("label", getattr(self.instance, "label", ""))
        if not slug:
            base_slug = slugify(label) if label else ""
            if not base_slug:
                base_slug = "plan"
            slug = base_slug
            suffix = 1
            while (
                PaymentPlan.objects.filter(
                    method=method,
                    context=attrs.get("context", self.instance.context),
                    slug=slug,
                )
                .exclude(id=getattr(self.instance, "id", None))
                .exists()
            ):
                suffix += 1
                slug = f"{base_slug}-{suffix}"
            attrs["slug"] = slug

        return attrs

    def create(self, validated_data: dict[str, Any]) -> PaymentPlan:
        method: WorkspacePaymentMethod = self.context["method"]
        plan = PaymentPlan.objects.create(method=method, **validated_data)
        adapter = _get_gateway_for_method(method)
        try:
            if adapter:
                adapter.ensure_plan_resources(method, plan)
        except Exception as exc:
            plan.metadata["plan_sync_error"] = str(exc)
            plan.save(update_fields=["metadata", "updated_at"])
            raise serializers.ValidationError({"stripe": str(exc)}) from exc
        return plan

    def update(self, instance: PaymentPlan, validated_data: dict[str, Any]) -> PaymentPlan:
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        adapter = _get_gateway_for_method(instance.method)
        try:
            if adapter:
                adapter.ensure_plan_resources(instance.method, instance)
        except Exception as exc:
            instance.metadata["plan_sync_error"] = str(exc)
            instance.save(update_fields=["metadata", "updated_at"])
            raise serializers.ValidationError({"stripe": str(exc)}) from exc
        return instance


class PublicPaymentPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentPlan
        fields = (
            "id",
            "slug",
            "label",
            "amount",
            "currency",
            "interval",
            "interval_count",
            "is_recurring",
            "custom_amount",
        )


class PublicPaymentMethodSerializer(serializers.ModelSerializer):
    provider = PaymentProviderSerializer(read_only=True)
    plans = serializers.SerializerMethodField()

    class Meta:
        model = WorkspacePaymentMethod
        fields = (
            "id",
            "display_name",
            "provider",
            "public_instructions",
            "enabled_contexts",
            "is_primary",
            # The currency donors are actually charged in — sourced from the
            # connected account's Account.default_currency at connect time
            # (SettlementCurrencyResolver). The public donate form labels its
            # amount field with this instead of assuming USD.
            "settlement_currency",
            "metadata",
            "plans",
        )

    def get_plans(self, obj: WorkspacePaymentMethod):
        filters = self.context.get("plan_filters", {})
        context_key = filters.get("context")
        recipient_id = filters.get("recipient_id")
        if not context_key:
            return []

        # The public list view prefetches the context-filtered active plans
        # (with recipients) into ``prefetched_context_plans`` — the recipient
        # narrowing then happens in Python over that small in-memory list, so
        # the donate-form endpoint stays at a constant query count (the old
        # per-method ``filter()`` + ``exists()`` + re-``filter()`` fired three
        # queries per method row). The query fallback covers direct
        # single-instance serialization (tests, ad-hoc callers) and mirrors
        # the prefetch exactly.
        plans = getattr(obj, "prefetched_context_plans", None)
        if plans is None:
            plans = list(obj.plans.filter(context=context_key, is_active=True).order_by("sort_order", "created_at"))

        if recipient_id:
            recipient_plans = [p for p in plans if str(p.recipient_id) == str(recipient_id)]
            plans = recipient_plans or [p for p in plans if p.recipient_id is None]
        else:
            plans = [p for p in plans if p.recipient_id is None]

        return PublicPaymentPlanSerializer(plans, many=True).data


def serialize_billing_plan(plan) -> dict:
    """Serialise a team Plan for the billing-plans endpoint.

    Numeric limits are derived from the data-driven ``Plan.limits`` map via
    the entitlements resolver. The legacy per-dimension keys are still
    emitted (derived) so the existing frontend contract is unchanged, and a
    forward-compatible ``limits`` map (all known dimensions, ``None`` =
    unlimited) is added alongside.
    """
    limits = EntitlementsResolver.resolve(plan_limits=getattr(plan, "limits", None)).as_dict()
    return {
        "pk": plan.pk,
        "title": plan.title,
        "max_projects_per_team": limits.get(EntitlementKey.MAX_PROJECTS_PER_TEAM.value),
        "max_members_per_team": limits.get(EntitlementKey.MAX_MEMBERS_PER_TEAM.value),
        "max_tasks_per_project": limits.get(EntitlementKey.MAX_TASKS_PER_PROJECT.value),
        "limits": limits,
        "price": plan.price,
        "currency": plan.currency,
        "billing_interval": plan.billing_interval,
        "interval_count": plan.interval_count,
        "is_default": plan.is_default,
    }

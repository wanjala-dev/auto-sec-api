from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TimestampedModel(models.Model):
    """Abstract base with created/updated timestamps."""

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PaymentProvider(TimestampedModel):
    """Catalog entry for a payment integration (Stripe, Braintree, etc.)."""

    API = "api"
    MANUAL = "manual"
    PROVIDER_TYPES = (
        (API, "API"),
        (MANUAL, "Manual"),
    )

    slug = models.SlugField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    provider_type = models.CharField(max_length=20, choices=PROVIDER_TYPES, default=API)
    description = models.TextField(blank=True)
    icon = models.URLField(max_length=500, blank=True)
    docs_url = models.URLField(max_length=500, blank=True)
    capabilities = models.JSONField(
        default=list,
        blank=True,
        help_text="List of supported contexts (donations, shop, sponsorship, etc.).",
    )
    config_template = models.JSONField(
        default=dict,
        blank=True,
        help_text="Schema describing configuration fields the frontend should collect.",
    )
    oauth_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific OAuth metadata (authorize URL, scopes, etc.).",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "workspace_payment_provider"
        ordering = ("display_name",)

    def __str__(self) -> str:
        return self.display_name


class WorkspacePaymentMethod(TimestampedModel):
    """Concrete payment method owned by a workspace."""

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_REQUIRES_ACTION = "requires_action"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_REQUIRES_ACTION, "Requires Action"),
        (STATUS_DISABLED, "Disabled"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="payment_methods")
    # tenant FK dropped in the auto-sec fork (single-DB, no tenants app).
    provider = models.ForeignKey(
        PaymentProvider,
        on_delete=models.PROTECT,
        related_name="workspace_methods",
    )
    contribution_means = models.ForeignKey(
        "workspaces.ContributionMeans",
        on_delete=models.SET_NULL,
        related_name="payment_methods",
        null=True,
        blank=True,
    )
    display_name = models.CharField(max_length=120)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_primary = models.BooleanField(default=False)
    primary_contexts = models.JSONField(
        default=list,
        blank=True,
        help_text="Contexts for which this method should be preferred.",
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Controls ordering when multiple methods are rendered to donors.",
    )
    enabled_contexts = models.JSONField(
        default=list,
        blank=True,
        help_text="List of contexts where this method can be used (donations, shop, etc.).",
    )
    provider_account_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider-specific identifier (e.g., Stripe account ID).",
    )
    settlement_currency = models.CharField(
        max_length=3,
        blank=True,
        null=True,
        help_text=(
            "ISO 4217 currency this payment method settles payouts in. "
            "For Stripe Connect, sourced from Account.default_currency "
            "at connect time. Nullable until backfilled; required for "
            "new methods going forward."
        ),
    )
    encrypted_credentials = models.TextField(
        blank=True,
        help_text="Encrypted blob containing API keys or OAuth tokens.",
    )
    public_instructions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Copy shown to donors for manual rails (mailing address, memo notes).",
    )
    allow_public_listing = models.BooleanField(
        default=False,
        help_text="Expose manual/offline methods to the public catalog when enabled.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Backend-only metadata (capabilities, defaults, etc.).",
    )
    last_error = models.TextField(
        blank=True,
        help_text="Latest connection or webhook error message for surfacing in admin UI.",
    )
    last_error_at = models.DateTimeField(null=True, blank=True)
    credentials_updated_at = models.DateTimeField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    platform_fee_bps = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            "Platform application fee in basis points (1bps = 0.01%). 0 means "
            "no fee — the default at launch. Used by Stripe Connect to set "
            "application_fee_amount on Checkout Sessions."
        ),
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payment_methods",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_payment_methods",
    )

    class Meta:
        db_table = "workspace_payment_method"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "provider", "provider_account_id"),
                name="unique_workspace_provider_account",
                condition=models.Q(provider_account_id__gt="", is_deleted=False),
            ),
            models.UniqueConstraint(
                fields=("workspace", "provider"),
                name="unique_workspace_primary_provider",
                condition=models.Q(is_primary=True, is_deleted=False),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.workspace.workspace_name} / {self.display_name}"


class PaymentWebhookEndpoint(TimestampedModel):
    """Webhook definitions per payment method."""

    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_DISABLED, "Disabled"),
    )

    method = models.ForeignKey(WorkspacePaymentMethod, on_delete=models.CASCADE, related_name="webhooks")
    name = models.CharField(
        max_length=80,
        help_text="Logical name (donations, sponsorship, shop, etc.).",
    )
    url = models.URLField(max_length=500)
    signing_secret = models.CharField(max_length=255)
    provider_endpoint_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Provider-side endpoint id (e.g. Stripe we_...) when the secret was "
            "captured from the provider at registration. Non-empty means the "
            "signing_secret is endpoint-specific and must never be overwritten "
            "with an env-level secret."
        ),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    last_error = models.TextField(blank=True)

    class Meta:
        db_table = "workspace_payment_webhook"
        unique_together = ("method", "name")
        ordering = ("method", "name")

    def __str__(self) -> str:
        return f"{self.method.display_name} - {self.name}"


class PaymentEvent(TimestampedModel):
    """Idempotency ledger for inbound provider events and transactions."""

    STATUS_RECEIVED = "received"
    STATUS_PROCESSING = "processing"
    STATUS_PROCESSED = "processed"
    STATUS_FAILED = "failed"
    STATUS_IGNORED = "ignored"
    STATUS_CHOICES = (
        (STATUS_RECEIVED, "Received"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_IGNORED, "Ignored"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=50, db_index=True)
    provider_account_id = models.CharField(max_length=255, blank=True, db_index=True)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.SET_NULL,
        related_name="payment_events",
        null=True,
        blank=True,
    )
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        on_delete=models.SET_NULL,
        related_name="payment_events",
        null=True,
        blank=True,
    )
    event_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider webhook event identifier when available.",
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Transaction/invoice/subscription id carried in the payload.",
    )
    event_type = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=10, blank=True)
    # Headroom for Stripe Adaptive Pricing (phase 2). When enabled,
    # ``currency``/``amount`` hold the *presentment* values (what the
    # buyer saw/paid in) and these three carry the *settlement* values
    # (what the seller receives after FX), plus the rate Stripe
    # applied. All nullable because classic single-currency flows
    # (v1) don't populate them — only Adaptive-Pricing writes do.
    presentment_currency = models.CharField(max_length=10, blank=True)
    settlement_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    fx_rate_applied = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
        help_text=(
            "Exchange rate Stripe applied when converting from the "
            "presentment currency to the seller's settlement currency. "
            "1.0 for same-currency flows."
        ),
    )
    payload = models.JSONField(default=dict, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )
    status_message = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_payment_event"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="unique_provider_event_id",
                condition=~Q(event_id=""),
            ),
            models.UniqueConstraint(
                fields=["provider", "external_id", "event_type"],
                name="unique_provider_external_event_type",
                condition=~Q(external_id="") & ~Q(event_type=""),
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalize ISO currency codes to upper-case before persisting.
        # Stripe Connect surfaces some payloads as `cad`/`usd` and others as
        # `CAD`/`USD`; without this, "sum by currency" queries silently
        # double-bucket. (2026-06-15 GTM audit.)
        for attr in ("currency", "presentment_currency"):
            value = getattr(self, attr, None)
            if value:
                normalized = value.strip().upper()
                if normalized != value:
                    setattr(self, attr, normalized)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        identifier = self.event_id or self.external_id or "unknown"
        return f"{self.provider}:{identifier}"


class PaymentOrder(TimestampedModel):
    """Internal order representing a request to collect money."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_REQUIRES_ACTION = "requires_action"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_REQUIRES_ACTION, "Requires Action"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.SET_NULL,
        related_name="payment_orders",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(
        "PaymentPlan",
        on_delete=models.SET_NULL,
        related_name="payment_orders",
        null=True,
        blank=True,
    )
    context = models.CharField(
        max_length=50,
        db_index=True,
        default="general",
        help_text="Business context for the order (workspace_support, campaign, etc.).",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=10, blank=True)
    customer_email = models.EmailField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)
    client_reference_id = models.CharField(max_length=255, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    metadata = models.JSONField(default=dict, blank=True)
    status_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_payment_order"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Order {self.id}"


class PaymentAttempt(TimestampedModel):
    """Gateway-specific attempt to fulfill a payment order."""

    STATUS_CREATED = "created"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_REQUIRES_ACTION = "requires_action"
    STATUS_CHOICES = (
        (STATUS_CREATED, "Created"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
        (STATUS_REQUIRES_ACTION, "Requires Action"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )
    provider = models.CharField(max_length=50, db_index=True)
    attempt_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_CREATED,
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=10, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    gateway_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider-generated identifier (session id, invoice id, etc.).",
    )
    gateway_reference_type = models.CharField(max_length=50, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    status_message = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_payment_attempt"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("order", "attempt_number"),
                name="unique_payment_attempt_number",
            ),
        ]

    def __str__(self) -> str:
        return f"Attempt {self.id} ({self.provider})"


class PaymentTransaction(TimestampedModel):
    """Immutable record of a provider event for a payment attempt."""

    STATUS_RECEIVED = "received"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_IGNORED = "ignored"
    STATUS_PENDING = "pending"
    STATUS_CHOICES = (
        (STATUS_RECEIVED, "Received"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_IGNORED, "Ignored"),
        (STATUS_PENDING, "Pending"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(
        PaymentAttempt,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    payment_event = models.ForeignKey(
        PaymentEvent,
        on_delete=models.SET_NULL,
        related_name="transactions",
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=50, db_index=True)
    event_type = models.CharField(max_length=120, blank=True)
    provider_event_id = models.CharField(max_length=255, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )
    provider_status = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    currency = models.CharField(max_length=10, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_payment_transaction"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["provider", "provider_event_id"], name="payment_txn_event_idx"),
            models.Index(fields=["provider", "external_id"], name="payment_txn_external_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"],
                name="unique_payment_txn_provider_event",
                condition=~Q(provider_event_id=""),
            ),
            models.UniqueConstraint(
                fields=["provider", "external_id", "event_type"],
                name="unique_payment_txn_external_event_type",
                condition=~Q(external_id="") & ~Q(event_type=""),
            ),
        ]

    def __str__(self) -> str:
        identifier = self.external_id or self.provider_event_id or str(self.id)
        return f"{self.provider}:{identifier}"


class DonationForm(TimestampedModel):
    """A standalone, shareable donation page.

    Owns its amount tiers as ``PaymentPlan`` rows (``context='donation_form'``,
    linked via ``PaymentPlan.donation_form``). Presentation + config live here;
    the money path reuses the workspace's payment method and the generic
    plan-sync / checkout machinery (no provider coupling at this layer).
    """

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    )

    VISIBILITY_PUBLIC = "public"
    VISIBILITY_UNLISTED = "unlisted"
    VISIBILITY_CHOICES = (
        (VISIBILITY_PUBLIC, "Public"),
        (VISIBILITY_UNLISTED, "Unlisted"),
    )

    ADDON_NONE = "none"
    ADDON_TIP = "tip"
    ADDON_COVER_FEES = "cover_fees"
    DONOR_ADDON_CHOICES = (
        (ADDON_NONE, "None"),
        (ADDON_TIP, "Tip"),
        (ADDON_COVER_FEES, "Cover fees"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="donation_forms",
    )
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        on_delete=models.SET_NULL,
        related_name="donation_forms",
        null=True,
        blank=True,
        help_text=(
            "Gateway the form charges through. Null = resolve the workspace's "
            "primary method for the donation context at checkout."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_donation_forms",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    slug = models.SlugField(max_length=80)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES, default=VISIBILITY_PUBLIC)
    donor_add_on = models.CharField(
        max_length=16,
        choices=DONOR_ADDON_CHOICES,
        default=ADDON_NONE,
        help_text="The single optional 'give extra' ask (mutually exclusive).",
    )
    allow_custom_amount = models.BooleanField(default=True)
    recurring_upsell_enabled = models.BooleanField(
        default=False,
        help_text="Prompt one-time donors to convert to monthly before checkout.",
    )
    thank_you_message = models.TextField(blank=True)
    auto_tags = models.JSONField(
        default=list,
        blank=True,
        help_text="Tags applied to the donor contact on a successful gift via this form.",
    )
    designations = models.JSONField(
        default=list,
        blank=True,
        help_text=("Designation refs the donor may route the gift to. Empty = general/workspace fund only (Slice 1)."),
    )
    response_count = models.PositiveIntegerField(
        default=0,
        help_text="Materialized count of successful donations attributed to this form.",
    )
    amount_raised = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=(
            "Materialized sum of GIFT amounts (tip-excluded) attributed to this "
            "form, in the connected-account currency. Bumped by the attribution "
            "handler off the gift amount stamped in the checkout metadata."
        ),
    )
    metadata = models.JSONField(default=dict, blank=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "donation_form"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "slug"),
                condition=Q(is_deleted=False),
                name="unique_donation_form_slug_per_workspace",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.slug})"


class DonationFormTemplate(TimestampedModel):
    """A reusable blueprint for a donation form (Template Kernel kind).

    A *starter* the admin picks from the gallery to pre-fill the donation-form
    builder. STRICTLY a blueprint — it is NOT a live form, owns no tiers/plans,
    and never touches the donation/checkout/webhook path. The builder reads the
    ``config`` JSON to seed a fresh draft, then the admin customises + attaches
    real designations.

    Scoping follows the kernel rule: ``workspace IS NULL`` = system (global)
    template; otherwise workspace-owned. ``config`` mirrors the frontend
    ``formTemplates.ts`` shape: ``{title, description, slug, donorAddOn,
    allowCustomAmount, tiers: {one_time[], monthly[], annual[]}}``.
    """

    DEFAULT_CATEGORY = "Donation forms"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="donation_form_templates",
        null=True,
        blank=True,
        help_text="Null = system (global) template; otherwise workspace-owned.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_donation_form_templates",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=80, default=DEFAULT_CATEGORY)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Builder pre-fill blueprint: title, description, slug, donorAddOn, "
            "allowCustomAmount, and tiers by frequency."
        ),
    )
    is_system = models.BooleanField(default=False, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "donation_form_template"
        ordering = ("name",)
        indexes = [
            models.Index(
                fields=["workspace", "is_deleted"],
                name="dform_tmpl_ws_deleted_idx",
            ),
        ]

    def __str__(self) -> str:
        scope = "system" if self.workspace_id is None else "workspace"
        return f"{self.name} ({scope})"


class PaymentPlan(TimestampedModel):
    """Recurring or one-time pricing defined for a payment method."""

    CONTEXT_RECIPIENT_SPONSORSHIP = "recipient_sponsorship"
    CONTEXT_PROJECT_SPONSORSHIP = "project_sponsorship"
    CONTEXT_WORKSPACE_SUPPORT = "workspace_support"
    CONTEXT_CAMPAIGN = "campaign"
    CONTEXT_TEAM_PLAN = "team_plan"
    CONTEXT_SHOP = "shop"
    CONTEXT_EVENT = "event"
    CONTEXT_EVENT_TICKET = "event_ticket"
    CONTEXT_DONATION_FORM = "donation_form"
    CONTEXT_CHOICES = (
        (CONTEXT_RECIPIENT_SPONSORSHIP, "Recipient Sponsorship"),
        (CONTEXT_PROJECT_SPONSORSHIP, "Project Sponsorship"),
        (CONTEXT_WORKSPACE_SUPPORT, "Workspace Support"),
        (CONTEXT_CAMPAIGN, "Campaign"),
        (CONTEXT_TEAM_PLAN, "Team Plan"),
        (CONTEXT_SHOP, "Marketplace / Shop"),
        (CONTEXT_EVENT, "Event"),
        (CONTEXT_EVENT_TICKET, "Event Ticket"),
        (CONTEXT_DONATION_FORM, "Donation Form"),
    )

    INTERVAL_MONTH = "month"
    INTERVAL_YEAR = "year"
    INTERVAL_WEEK = "week"
    INTERVAL_DAY = "day"
    INTERVAL_CHOICES = (
        (INTERVAL_MONTH, "Monthly"),
        (INTERVAL_YEAR, "Yearly"),
        (INTERVAL_WEEK, "Weekly"),
        (INTERVAL_DAY, "Daily"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        related_name="plans",
        on_delete=models.CASCADE,
    )
    context = models.CharField(max_length=50, choices=CONTEXT_CHOICES)
    slug = models.SlugField(max_length=80)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.50"))],
    )
    currency = models.CharField(max_length=10, default="usd")
    interval = models.CharField(
        max_length=20,
        choices=INTERVAL_CHOICES,
        blank=True,
    )
    interval_count = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Number of intervals between recurring charges (e.g., 2 for biweekly).",
    )
    is_recurring = models.BooleanField(default=True)
    custom_amount = models.BooleanField(
        default=False,
        help_text="Allow donor to enter their own amount (price is created dynamically).",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    product_id = models.CharField(max_length=255, blank=True)
    price_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # recipient FK dropped in the auto-sec fork (sponsorship recipients removed).
    donation_form = models.ForeignKey(
        "DonationForm",
        related_name="tier_plans",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text=(
            "Set when this plan is a tier owned by a Donation Form "
            "(context='donation_form'). Null for all other plan contexts."
        ),
    )

    class Meta:
        db_table = "workspace_payment_plan"
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("method", "context", "slug"),
                name="unique_plan_per_context",
            ),
            # Tier slugs are unique within a single Donation Form. Additive
            # partial constraint — leaves the existing (non-form) plan
            # uniqueness untouched.
            models.UniqueConstraint(
                fields=("donation_form", "slug"),
                condition=Q(donation_form__isnull=False),
                name="unique_donation_form_tier_slug",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.method.display_name} / {self.label}"


class PaymentRefund(TimestampedModel):
    """Provider-agnostic refund record linked to a payment transaction."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    )

    REASON_REQUESTED_BY_CUSTOMER = "requested_by_customer"
    REASON_DUPLICATE = "duplicate"
    REASON_FRAUDULENT = "fraudulent"
    REASON_OTHER = "other"
    REASON_CHOICES = (
        (REASON_REQUESTED_BY_CUSTOMER, "Requested by Customer"),
        (REASON_DUPLICATE, "Duplicate"),
        (REASON_FRAUDULENT, "Fraudulent"),
        (REASON_OTHER, "Other"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.CASCADE,
        related_name="refunds",
    )
    attempt = models.ForeignKey(
        PaymentAttempt,
        on_delete=models.CASCADE,
        related_name="refunds",
    )
    payment_event = models.ForeignKey(
        PaymentEvent,
        on_delete=models.SET_NULL,
        related_name="refunds",
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reason = models.CharField(max_length=50, choices=REASON_CHOICES, default=REASON_OTHER)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10)
    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Provider refund identifier.",
    )
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_payment_refund"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_payment_refund_external",
                condition=~Q(external_id=""),
            ),
        ]

    def __str__(self) -> str:
        return f"Refund {self.id} ({self.provider}:{self.external_id or 'pending'})"


class PaymentDispute(TimestampedModel):
    """Provider-agnostic dispute/chargeback record."""

    STATUS_WARNING_NEEDS_RESPONSE = "warning_needs_response"
    STATUS_WARNING_UNDER_REVIEW = "warning_under_review"
    STATUS_NEEDS_RESPONSE = "needs_response"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_WON = "won"
    STATUS_LOST = "lost"
    STATUS_ACCEPTED = "accepted"
    STATUS_CHOICES = (
        (STATUS_WARNING_NEEDS_RESPONSE, "Warning — Needs Response"),
        (STATUS_WARNING_UNDER_REVIEW, "Warning — Under Review"),
        (STATUS_NEEDS_RESPONSE, "Needs Response"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_WON, "Won"),
        (STATUS_LOST, "Lost"),
        (STATUS_ACCEPTED, "Accepted"),
    )

    CATEGORY_GENERAL = "general"
    CATEGORY_FRAUDULENT = "fraudulent"
    CATEGORY_DUPLICATE = "duplicate"
    CATEGORY_PRODUCT_NOT_RECEIVED = "product_not_received"
    CATEGORY_PRODUCT_UNACCEPTABLE = "product_unacceptable"
    CATEGORY_SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    CATEGORY_UNRECOGNIZED = "unrecognized"
    CATEGORY_CREDIT_NOT_PROCESSED = "credit_not_processed"
    CATEGORY_CHOICES = (
        (CATEGORY_GENERAL, "General"),
        (CATEGORY_FRAUDULENT, "Fraudulent"),
        (CATEGORY_DUPLICATE, "Duplicate"),
        (CATEGORY_PRODUCT_NOT_RECEIVED, "Product Not Received"),
        (CATEGORY_PRODUCT_UNACCEPTABLE, "Product Unacceptable"),
        (CATEGORY_SUBSCRIPTION_CANCELLED, "Subscription Cancelled"),
        (CATEGORY_UNRECOGNIZED, "Unrecognized"),
        (CATEGORY_CREDIT_NOT_PROCESSED, "Credit Not Processed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.CASCADE,
        related_name="disputes",
    )
    payment_event = models.ForeignKey(
        PaymentEvent,
        on_delete=models.SET_NULL,
        related_name="disputes",
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_NEEDS_RESPONSE)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_GENERAL)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10)
    external_id = models.CharField(
        max_length=255,
        help_text="Provider dispute identifier.",
    )
    evidence_due_by = models.DateTimeField(null=True, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "workspace_payment_dispute"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_payment_dispute_external",
                condition=~Q(external_id=""),
            ),
        ]

    def __str__(self) -> str:
        return f"Dispute {self.id} ({self.provider}:{self.status})"


class PaymentFee(TimestampedModel):
    """Platform fee recorded against a payment transaction."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.CASCADE,
        related_name="fees",
    )
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        on_delete=models.CASCADE,
        related_name="fees",
    )
    provider = models.CharField(max_length=50)
    context = models.CharField(
        max_length=50,
        default="general",
        help_text="Revenue source context (donations, shop, campaign, event, etc.).",
    )
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0"))
    fixed_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    capped_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum fee cap; NULL means uncapped.",
    )
    sales_tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sales_tax_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0"))
    currency = models.CharField(max_length=10)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "workspace_payment_fee"
        ordering = ("-created_at",)
        constraints = [
            # One fee per payment-transaction per context. This is the real
            # idempotency guarantee for revenue-share fee recording: the
            # PaymentSucceeded handler runs under acks_late=True and a gift
            # fires multiple success events (checkout + charge + invoice), so a
            # read-then-write pre-check is a TOCTOU under concurrent / redelivered
            # tasks. The DB constraint makes the duplicate insert fail instead.
            models.UniqueConstraint(
                fields=["transaction", "context"],
                name="unique_payment_fee_transaction_context",
            ),
        ]

    def __str__(self) -> str:
        return f"Fee {self.fee_amount} {self.currency} on {self.transaction_id}"


class PaymentPayout(TimestampedModel):
    """Tracks money disbursed from the platform to a workspace bank account."""

    STATUS_PENDING = "pending"
    STATUS_IN_TRANSIT = "in_transit"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_TRANSIT, "In Transit"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELED, "Canceled"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="payment_payouts",
    )
    method = models.ForeignKey(
        WorkspacePaymentMethod,
        on_delete=models.CASCADE,
        related_name="payouts",
    )
    provider = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10)
    external_id = models.CharField(
        max_length=255,
        help_text="Provider payout identifier.",
    )
    failure_code = models.CharField(max_length=255, blank=True)
    failure_message = models.TextField(blank=True)
    arrival_date = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "workspace_payment_payout"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_payment_payout_external",
                condition=~Q(external_id=""),
            ),
        ]

    def __str__(self) -> str:
        return f"Payout {self.id} ({self.provider}:{self.status})"


class PaymentBalanceTransaction(TimestampedModel):
    """Immutable audit-trail entry for every money movement on the platform."""

    TYPE_PAYMENT = "payment"
    TYPE_REFUND = "refund"
    TYPE_DISPUTE = "dispute"
    TYPE_DISPUTE_REVERSAL = "dispute_reversal"
    TYPE_PAYOUT = "payout"
    TYPE_FEE = "fee"
    TYPE_FEE_REFUND = "fee_refund"
    TYPE_ADJUSTMENT = "adjustment"
    TYPE_CHOICES = (
        (TYPE_PAYMENT, "Payment"),
        (TYPE_REFUND, "Refund"),
        (TYPE_DISPUTE, "Dispute"),
        (TYPE_DISPUTE_REVERSAL, "Dispute Reversal"),
        (TYPE_PAYOUT, "Payout"),
        (TYPE_FEE, "Fee"),
        (TYPE_FEE_REFUND, "Fee Refund"),
        (TYPE_ADJUSTMENT, "Adjustment"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="payment_balance_transactions",
    )
    transaction_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    source_type = models.CharField(
        max_length=50,
        help_text="Model type of the source (e.g. PaymentTransaction, PaymentRefund, PaymentDispute).",
    )
    source_id = models.UUIDField(
        help_text="Primary key of the source record.",
    )
    provider = models.CharField(max_length=50, blank=True)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Gross amount (positive for credits, negative for debits).",
    )
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    net = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="amount - fee",
    )
    currency = models.CharField(max_length=10)
    external_id = models.CharField(max_length=255, blank=True)
    available_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When these funds become available for payout.",
    )
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "workspace_payment_balance_transaction"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["source_type", "source_id"], name="payment_bal_txn_source_idx"),
            models.Index(fields=["workspace", "transaction_type"], name="payment_bal_txn_ws_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_type} {self.amount} {self.currency}"

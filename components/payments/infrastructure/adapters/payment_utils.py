from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import connection
from django.db.models import Q

from infrastructure.persistence.workspaces.payments.models import PaymentProvider, WorkspacePaymentMethod

ZERO_DECIMAL_CURRENCIES = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}


def stripe_amount_to_decimal(amount: object | None, currency: str | None) -> Decimal | None:
    """
    Convert a Stripe minor-unit amount into a Decimal in major units.

    CONSTRAINTS:
    - Expects Stripe amounts (integers) in the smallest currency unit.
    - Zero-decimal currencies are returned without scaling.
    - Returns None when amount is missing or invalid.
    """
    if amount is None:
        return None
    try:
        decimal_amount = Decimal(str(amount))
    except (TypeError, ValueError, ArithmeticError):
        return None

    currency_code = (currency or "usd").lower()
    exponent = 0 if currency_code in ZERO_DECIMAL_CURRENCIES else 2
    divisor = Decimal(10) ** exponent
    quantizer = Decimal("1") if exponent == 0 else Decimal("0.01")
    return (decimal_amount / divisor).quantize(quantizer)


def decimal_to_stripe_amount(amount: object | None, currency: str | None) -> int | None:
    """
    Convert a major-unit amount into Stripe minor units.

    CONSTRAINTS:
    - Accepts Decimal/str/number inputs representing major units (e.g., 10.50 USD).
    - Zero-decimal currencies are returned without scaling.
    - Returns None when amount is missing or invalid.
    """
    if amount is None:
        return None
    try:
        decimal_amount = Decimal(str(amount))
    except (TypeError, ValueError, ArithmeticError):
        return None

    currency_code = (currency or "usd").lower()
    exponent = 0 if currency_code in ZERO_DECIMAL_CURRENCIES else 2
    multiplier = Decimal(10) ** exponent
    quantizer = Decimal("1") if exponent == 0 else Decimal("0.01")
    try:
        decimal_amount = decimal_amount.quantize(quantizer, rounding=ROUND_HALF_UP)
    except (ArithmeticError, ValueError):
        return None
    return int((decimal_amount * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_workspace_payment_method(
    workspace,
    context: str = "donations",
    preferred_method_id: str | None = None,
    provider_slug: str | None = None,
) -> WorkspacePaymentMethod | None:
    """
    Locate the best WorkspacePaymentMethod for the supplied workspace. This prefers an
    explicitly provided method id, otherwise falls back to the workspace's primary
    method that supports the requested context. Manual/offline providers are
    excluded because checkout flows require API-backed methods.
    """
    queryset = WorkspacePaymentMethod.objects.filter(
        workspace=workspace,
        status=WorkspacePaymentMethod.STATUS_ACTIVE,
        is_deleted=False,
        provider__provider_type=PaymentProvider.API,
    )

    if provider_slug:
        queryset = queryset.filter(provider__slug=provider_slug)

    supports_json_contains = getattr(
        connection.features, "supports_json_field_contains", False
    )
    if context and supports_json_contains:
        queryset = queryset.filter(
            Q(enabled_contexts__contains=[context]) | Q(enabled_contexts=[])
        )

    if preferred_method_id:
        try:
            method = queryset.get(id=preferred_method_id)
            if context and not supports_json_contains:
                enabled_contexts = method.enabled_contexts or []
                if enabled_contexts and context not in enabled_contexts:
                    raise WorkspacePaymentMethod.DoesNotExist
            return method
        except WorkspacePaymentMethod.DoesNotExist:
            pass

    if context and not supports_json_contains:
        candidates = list(queryset)

        def _supports_context(method):
            contexts = method.enabled_contexts or []
            return not contexts or context in contexts

        def _primary_for_context(method):
            contexts = method.primary_contexts or []
            return context in contexts

        def _sort_key(method):
            return (method.sort_order or 0, method.created_at)

        candidates = [method for method in candidates if _supports_context(method)]
        if not candidates:
            return None

        primary_context = [method for method in candidates if _primary_for_context(method)]
        if primary_context:
            return sorted(primary_context, key=_sort_key)[0]

        primary = [method for method in candidates if method.is_primary]
        if primary:
            return sorted(primary, key=_sort_key)[0]

        return sorted(candidates, key=_sort_key)[0]

    if context:
        method = (
            queryset.filter(primary_contexts__contains=[context])
            .order_by("sort_order", "created_at")
            .first()
        )
        if method:
            return method

    method = queryset.filter(is_primary=True).order_by("sort_order").first()
    if method:
        return method

    return queryset.order_by("sort_order", "created_at").first()


def resolve_db_alias_for_stripe_account(account_id: str | None) -> str | None:
    """
    Locate the database alias that owns a Stripe Connect account id.

    CONSTRAINTS:
    - Only searches configured database aliases; skips aliases that are offline.
    - Matches on active, non-deleted Stripe payment methods.
    - Returns None when no matching method is found.
    """
    if not account_id:
        return None

    aliases = list(getattr(settings, "DATABASES", {}).keys())
    if "default" in aliases:
        aliases = [alias for alias in aliases if alias != "default"] + ["default"]

    for alias in aliases:
        try:
            exists = WorkspacePaymentMethod.objects.using(alias).filter(
                provider__slug__istartswith="stripe",
                provider_account_id=account_id,
                status=WorkspacePaymentMethod.STATUS_ACTIVE,
                is_deleted=False,
            ).exists()
        except Exception:
            continue
        if exists:
            return alias

    return None

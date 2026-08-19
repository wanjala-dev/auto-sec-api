from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.models import Q

from components.payments.infrastructure.services.stripe_invoice_helpers import (
    resolve_invoice_subscription_id,
)
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import (
    PaymentEvent,
    PaymentProvider,
    WorkspacePaymentMethod,
)

logger = logging.getLogger(__name__)

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

    supports_json_contains = getattr(connection.features, "supports_json_field_contains", False)
    if context and supports_json_contains:
        queryset = queryset.filter(Q(enabled_contexts__contains=[context]) | Q(enabled_contexts=[]))

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
        method = queryset.filter(primary_contexts__contains=[context]).order_by("sort_order", "created_at").first()
        if method:
            return method

    method = queryset.filter(is_primary=True).order_by("sort_order").first()
    if method:
        return method

    return queryset.order_by("sort_order", "created_at").first()


def payment_event_write_alias() -> str:
    """The DB alias the CURRENTLY BOUND tenant writes payment events to.

    A webhook handler must open its transaction on the same connection its
    writes land on: under the tenant router a bare ``transaction.atomic()``
    only opens a transaction on ``default``, so a bound dedicated tenant would
    write outside any transaction (and its ``on_commit`` hooks would fire
    against the wrong connection). Ask the router rather than assuming.
    """
    from components.shared_kernel.application.transactional import db_alias_for

    return db_alias_for(PaymentEvent)


#: The platform (non-Connect) Stripe events the team-plan webhook actually ACTS
#: on — the six keys of ``TeamPlanWebhookRepository.handle_verified_webhook``'s
#: handler map. Only these can *lose money* by being handled against the wrong
#: database, so only these make an unresolvable tenant a hard failure. Anything
#: else (``customer.subscription.created``, ``price.updated``, …) is recorded
#: for audit and ignored, exactly as before.
PLATFORM_BILLING_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.expired",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "customer.subscription.deleted",
        "customer.subscription.updated",
    }
)

#: Claim rungs in precedence order, most authoritative first.
#:
#: ``workspace_id`` is a UUID **we** wrote into the checkout session's metadata
#: (``team_plan_billing_repository`` builds it), so it is the only claim that is
#: ours rather than Stripe's. ``subscription_id`` and ``customer_id`` are
#: Stripe's, stamped onto the ``Workspace`` row by ``apply_team_plan_purchase``
#: / checkout creation. The ladder matters because the FIRST event of a new
#: subscription (``checkout.session.completed``) carries the workspace id before
#: any subscription id exists to match on.
CLAIM_RUNGS = ("workspace_id", "subscription_id", "customer_id")


@dataclass(frozen=True)
class BillingTenantRouting:
    """Which database owns a platform billing event — and how sure we are.

    ``alias is None`` never means "use the pool". It means *unresolved*, and
    when ``must_resolve`` is true the caller has to fail loudly rather than
    write somewhere on a guess.
    """

    alias: str | None = None
    #: Which entry of :data:`CLAIM_RUNGS` produced ``alias``.
    matched_on: str | None = None
    #: The claim values the event carried, rung → value. Empty when the event
    #: names nothing we can route on.
    claims: dict[str, str] = field(default_factory=dict)
    #: True when this event type moves money AND carried at least one claim —
    #: i.e. failing to resolve it is a billing outage, not a no-op.
    must_resolve: bool = False
    event_id: str | None = None
    event_type: str | None = None
    #: More than one database claimed the same rung. Refusing to pick is the
    #: point: guessing between two tenants on a money path is the failure this
    #: whole resolver exists to prevent.
    ambiguous_aliases: tuple[str, ...] = ()
    #: Aliases whose scan raised (offline database, missing table). Their rows
    #: were NOT searched, so "not found" cannot be trusted — which is the
    #: single strongest argument for answering Stripe with a retryable status.
    unreachable_aliases: tuple[str, ...] = ()
    scanned_aliases: tuple[str, ...] = ()

    @property
    def unresolved(self) -> bool:
        """A money-moving event we could not attribute to any database."""
        return self.must_resolve and self.alias is None


def _payload_get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` off a Stripe payload node (dict, StripeObject, or object)."""
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _payload_id(value: Any) -> str | None:
    """Normalise a Stripe reference that may be an id string or an expanded object."""
    if isinstance(value, Mapping):
        value = value.get("id")
    elif value is not None and not isinstance(value, str):
        value = getattr(value, "id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def extract_platform_billing_claims(event: Any) -> dict[str, str]:
    """Pull every tenant-identifying claim a platform billing event carries.

    Returns a rung → value mapping restricted to :data:`CLAIM_RUNGS`; rungs the
    event does not carry are absent. Knows Stripe's payload shape so no other
    layer has to.
    """
    event_type = _payload_get(event, "type") or ""
    data = _payload_get(event, "data") or {}
    obj = _payload_get(data, "object") or {}

    claims: dict[str, str] = {}

    metadata = _payload_get(obj, "metadata") or {}
    workspace_id = _payload_get(metadata, "workspace_id")
    if isinstance(workspace_id, str) and workspace_id.strip():
        claims["workspace_id"] = workspace_id.strip()

    if event_type.startswith("customer.subscription."):
        # The event object IS the subscription.
        subscription_id = _payload_id(_payload_get(obj, "id"))
    elif event_type.startswith("invoice."):
        # Stripe has moved this field three times; reuse the one walker that
        # already knows every location rather than adding a fourth guess.
        subscription_id = resolve_invoice_subscription_id(obj) if isinstance(obj, Mapping) else None
    else:
        subscription_id = _payload_id(_payload_get(obj, "subscription"))
    if subscription_id:
        claims["subscription_id"] = subscription_id

    customer_id = _payload_id(_payload_get(obj, "customer"))
    if customer_id:
        claims["customer_id"] = customer_id

    return claims


def _claims_filter(claims: Mapping[str, str]) -> Q | None:
    """One OR'd predicate per scanned alias, so the scan costs N queries not 3N."""
    predicate = Q()
    matched_any = False

    workspace_id = claims.get("workspace_id")
    if workspace_id:
        try:
            uuid.UUID(str(workspace_id))
        except (TypeError, ValueError):
            # Metadata is attacker-adjacent (it round-trips through Stripe);
            # a non-UUID would make the queryset raise rather than miss.
            logger.warning("platform_billing_claim_bad_workspace_id value=%s", workspace_id)
        else:
            predicate |= Q(id=workspace_id)
            matched_any = True

    subscription_id = claims.get("subscription_id")
    if subscription_id:
        predicate |= Q(stripe_subscription_id=subscription_id)
        matched_any = True

    customer_id = claims.get("customer_id")
    if customer_id:
        predicate |= Q(stripe_customer_id=customer_id)
        matched_any = True

    return predicate if matched_any else None


def resolve_db_alias_for_platform_billing_event(event: Any) -> BillingTenantRouting:
    """Locate the database that owns the workspace a platform billing event is about.

    THE PROBLEM. Stripe POSTs platform (non-Connect) subscription events to one
    fixed URL with no tenant subdomain, so ``TenantHostMiddleware`` binds the
    pooled console. ``resolve_db_alias_for_stripe_account`` cannot help: a
    platform event carries no connected account, only a customer. A dedicated
    tenant's own subscription event therefore looked for its workspace in the
    POOL, found nothing, and was marked "Missing workspace for Stripe webhook"
    with a 200 back to Stripe — a silent, unretried billing drop.

    THE SHAPE. Same honest cross-alias scan as the account resolver
    (``.using(alias)`` per configured database, ``default`` last so the two
    resolvers cannot disagree about precedence), but climbing a claim ladder —
    see :data:`CLAIM_RUNGS`. One OR'd query per alias, then a deterministic
    pick by rung.

    COST. O(number of configured aliases) queries per platform webhook, each an
    indexed lookup on a column ``Workspace`` already carries. That is correct
    but not free, and it grows linearly with the dedicated tier. The long-term
    answer is a control-plane routing index in the tenant registry (customer id
    / subscription id → db alias, written when checkout stamps the customer),
    which makes this an O(1) lookup in ``default`` and needs no fan-out —
    proposed, not built here.
    """
    event_type = _payload_get(event, "type") or None
    event_id = _payload_id(_payload_get(event, "id"))
    claims = extract_platform_billing_claims(event)
    must_resolve = bool(claims) and event_type in PLATFORM_BILLING_EVENT_TYPES

    predicate = _claims_filter(claims)
    if predicate is None:
        return BillingTenantRouting(
            claims=claims,
            must_resolve=False,
            event_id=event_id,
            event_type=event_type,
        )

    aliases = list(getattr(settings, "DATABASES", {}).keys())
    if "default" in aliases:
        aliases = [alias for alias in aliases if alias != "default"] + ["default"]

    hits: dict[str, list[str]] = {rung: [] for rung in CLAIM_RUNGS}
    unreachable: list[str] = []

    for alias in aliases:
        try:
            rows = list(
                # ``all_objects()`` deliberately, not ``objects``: the default
                # manager hides ``status != "active"`` workspaces, and routing
                # is a question about WHICH DATABASE, not about workspace
                # state. Scoping the scan would turn a deactivated tenant's
                # event into an unresolvable one — an infinite Stripe retry for
                # an event the handler would simply have ignored.
                Workspace.objects.all_objects()
                .using(alias)
                .filter(predicate)
                .values_list("id", "stripe_subscription_id", "stripe_customer_id")[:50]
            )
        except Exception:
            # An unreachable alias is NOT a miss — its rows were never
            # searched. Recorded so the caller can tell "unknown customer"
            # from "could not look".
            logger.exception("platform_billing_alias_scan_failed alias=%s event_id=%s", alias, event_id)
            unreachable.append(alias)
            continue
        for row_id, row_subscription, row_customer in rows:
            if claims.get("workspace_id") and str(row_id) == claims["workspace_id"]:
                hits["workspace_id"].append(alias)
            if claims.get("subscription_id") and row_subscription == claims["subscription_id"]:
                hits["subscription_id"].append(alias)
            if claims.get("customer_id") and row_customer == claims["customer_id"]:
                hits["customer_id"].append(alias)

    base = BillingTenantRouting(
        claims=claims,
        must_resolve=must_resolve,
        event_id=event_id,
        event_type=event_type,
        unreachable_aliases=tuple(unreachable),
        scanned_aliases=tuple(aliases),
    )

    for rung in CLAIM_RUNGS:
        matched = sorted(set(hits[rung]), key=aliases.index)
        if not matched:
            continue
        if len(matched) > 1:
            logger.error(
                "platform_billing_claim_ambiguous rung=%s aliases=%s event_id=%s",
                rung,
                ",".join(matched),
                event_id,
            )
            return replace(base, ambiguous_aliases=tuple(matched))
        alias = matched[0]
        disagreeing = sorted(
            {other for lower in CLAIM_RUNGS for other in set(hits[lower]) if other != alias},
        )
        if disagreeing:
            # The rungs point at different databases. The ladder still decides
            # (deterministically), but stale billing ids spread across tenants
            # is a data problem someone should look at.
            logger.warning(
                "platform_billing_claim_disagreement chosen=%s rung=%s others=%s event_id=%s",
                alias,
                rung,
                ",".join(disagreeing),
                event_id,
            )
        return replace(base, alias=alias, matched_on=rung)

    return base


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
            exists = (
                WorkspacePaymentMethod.objects.using(alias)
                .filter(
                    provider__slug__istartswith="stripe",
                    provider_account_id=account_id,
                    status=WorkspacePaymentMethod.STATUS_ACTIVE,
                    is_deleted=False,
                )
                .exists()
            )
        except Exception:
            continue
        if exists:
            return alias

    return None

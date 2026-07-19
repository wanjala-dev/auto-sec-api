"""API-v1 read shapes for the payments / billing surface (additive).

This module is the v1 boundary for every billing READ that emits money or a
normalizable datetime. It NEVER mutates the v0 output: each helper / serializer
is selected only when ``request.version == 'v1'`` and produces the C1 money
object + C4 ISO-8601-Z timestamps the v1 contract specifies. v0 callers (the
unversioned alias and ``/api/v0/...``) keep their exact byte shape.

Two money sources live in this surface, with OPPOSITE minor-unit semantics —
getting this wrong inflates or shrinks a figure 100×, so it is the load-bearing
decision of the whole migration:

* **Team-plan price** — ``Plan.price`` (IntegerField) and the derived
  ``PaymentPlan.amount`` (Decimal) are **MAJOR units** (whole dollars). The
  Stripe adapter calls ``decimal_to_stripe_amount(plan.amount, …)`` to multiply
  *up* to cents at charge time, which proves the stored value is major. These
  feed ``build_money_v1`` (major -> money object) directly.

* **Stripe invoice / subscription amounts** — ``amount_due`` / ``amount_paid``
  / ``amount_remaining`` on invoices and the upcoming-invoice / plan-preview
  ``amount_due`` come straight from Stripe, which ALWAYS expresses money in
  integer **minor units** (cents). These feed ``build_money_v1_from_minor``
  (minor -> money object) — passing them to ``build_money_v1`` would double-apply
  the exponent.

Stripe timestamps (``created``, ``period_start``, ``period_end``,
``current_period_end``, ``next_payment_attempt``) are **Unix epoch seconds**;
``_iso_utc_z_from_epoch`` normalizes them. ``Workspace.plan_end_date`` is a
Django ``DateTimeField`` (a Python datetime); ``_iso_utc_z`` handles it.
"""

from __future__ import annotations

import datetime
from datetime import timezone as _dt_timezone

from rest_framework import serializers

from components.money.mappers.rest.money_serializers import (
    build_money_v1,
    build_money_v1_from_minor,
)
from components.payments.mappers.rest.payment_serializers import (
    PaymentPlanSerializer,
    PublicPaymentMethodSerializer,
    PublicPaymentPlanSerializer,
)


def _iso_utc_z(dt) -> str | None:
    """C4: ISO-8601 in UTC with a ``Z`` suffix, seconds precision; null-safe.

    Mirrors the budgeting/sponsorship helper so every v1 timestamp serializes
    byte-identically across contexts. The project runs ``USE_TZ=False`` with
    ``TZ=UTC``, so naive datetimes are already UTC — we just stamp the ``Z``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:  # naive (project runs USE_TZ=False, TZ=UTC)
        return dt.replace(microsecond=0).isoformat() + "Z"
    return dt.astimezone(_dt_timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_utc_z_from_epoch(epoch) -> str | None:
    """C4 for a Stripe Unix-epoch-seconds integer; null-safe.

    Stripe timestamps are integer seconds since the epoch (UTC). Convert to a
    UTC datetime, then emit the same seconds-precision ISO-8601 ``Z`` shape as
    :func:`_iso_utc_z`. Non-numeric / ``None`` inputs return ``None`` (C8).
    """
    if epoch is None:
        return None
    try:
        seconds = int(epoch)
    except (TypeError, ValueError):
        return None
    dt = datetime.datetime.fromtimestamp(seconds, tz=_dt_timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── Controller-dict reshapers (billing reads emit money via inline dicts) ─────


def billing_plan_to_v1(plan_payload: dict | None) -> dict | None:
    """Reshape the ``plan`` block of the billing-overview response.

    ``plan_payload`` is the controller's
    ``{"id", "title", "price", "currency", "billing_interval", "interval_count"}``
    dict where ``price`` is a MAJOR-unit integer. Replaces ``price`` with a C1
    money object (currency from the plan's own ``currency``); leaves every other
    key untouched. ``None`` -> ``None`` (workspace has no plan).
    """
    if plan_payload is None:
        return None
    reshaped = dict(plan_payload)
    reshaped["price"] = build_money_v1(plan_payload.get("price"), plan_payload.get("currency"))
    return reshaped


def serialize_billing_plan_v1(plan_payload: dict) -> dict:
    """Reshape one ``serialize_billing_plan`` row (billing-plans list).

    The v0 row carries ``price`` (MAJOR-unit integer) + ``currency``. Replaces
    ``price`` with a C1 money object; entitlement / limit keys are untouched.
    """
    reshaped = dict(plan_payload)
    reshaped["price"] = build_money_v1(plan_payload.get("price"), plan_payload.get("currency"))
    return reshaped


def upcoming_invoice_to_v1(invoice_payload: dict | None) -> dict | None:
    """Reshape the ``upcoming_invoice`` block of billing-overview.

    ``amount_due`` is a Stripe MINOR-unit integer; ``next_payment_attempt`` is a
    Stripe Unix-epoch timestamp. ``None`` -> ``None`` (no upcoming invoice).
    """
    if invoice_payload is None:
        return None
    reshaped = dict(invoice_payload)
    reshaped["amount_due"] = build_money_v1_from_minor(
        invoice_payload.get("amount_due"), invoice_payload.get("currency")
    )
    reshaped["next_payment_attempt"] = _iso_utc_z_from_epoch(
        invoice_payload.get("next_payment_attempt")
    )
    return reshaped


def billing_overview_to_v1(payload: dict, *, workspace) -> dict:
    """Reshape the full billing-overview response dict for v1.

    * ``plan.price`` -> C1 money object (major source).
    * ``upcoming_invoice.amount_due`` -> C1 money object (Stripe minor source);
      its ``next_payment_attempt`` -> ISO-Z.
    * ``plan_end_date`` (Django ``DateTimeField``) -> ISO-Z.
    * ``current_period_end`` (Stripe epoch) -> ISO-Z.

    Identity / status fields (``workspace_id`` already a string UUID, the two
    Stripe id strings, ``plan_status``, ``subscription_status``) and the
    ``payment_methods`` list (cards: brand / last4 — no money) are unchanged.
    """
    reshaped = dict(payload)
    reshaped["plan"] = billing_plan_to_v1(payload.get("plan"))
    reshaped["upcoming_invoice"] = upcoming_invoice_to_v1(payload.get("upcoming_invoice"))
    reshaped["plan_end_date"] = _iso_utc_z(payload.get("plan_end_date"))
    reshaped["current_period_end"] = _iso_utc_z_from_epoch(payload.get("current_period_end"))
    return reshaped


def invoice_row_to_v1(row: dict) -> dict:
    """Reshape one billing-history invoice row.

    ``amount_due`` / ``amount_paid`` / ``amount_remaining`` are Stripe MINOR-unit
    integers (each labelled by the row's own ``currency``). ``created`` /
    ``period_start`` / ``period_end`` are Stripe Unix-epoch timestamps. The id,
    number, status, subscription, and the two URL fields are untouched.
    """
    currency = row.get("currency")
    reshaped = dict(row)
    reshaped["amount_due"] = build_money_v1_from_minor(row.get("amount_due"), currency)
    reshaped["amount_paid"] = build_money_v1_from_minor(row.get("amount_paid"), currency)
    reshaped["amount_remaining"] = build_money_v1_from_minor(row.get("amount_remaining"), currency)
    reshaped["created"] = _iso_utc_z_from_epoch(row.get("created"))
    reshaped["period_start"] = _iso_utc_z_from_epoch(row.get("period_start"))
    reshaped["period_end"] = _iso_utc_z_from_epoch(row.get("period_end"))
    return reshaped


def billing_history_to_v1(payload: dict) -> dict:
    """Reshape the full billing-history response dict — maps each invoice row."""
    reshaped = dict(payload)
    reshaped["invoices"] = [invoice_row_to_v1(row) for row in payload.get("invoices", [])]
    return reshaped


def plan_preview_to_v1(payload: dict) -> dict:
    """Reshape the plan-preview response dict.

    ``amount_due`` is a Stripe MINOR-unit integer; ``next_payment_attempt`` is a
    Stripe Unix-epoch timestamp. ``lines`` is Stripe's raw invoice-line payload
    (opaque nested provider data) — left untouched, exactly as v0 returns it.
    """
    reshaped = dict(payload)
    reshaped["amount_due"] = build_money_v1_from_minor(
        payload.get("amount_due"), payload.get("currency")
    )
    reshaped["next_payment_attempt"] = _iso_utc_z_from_epoch(payload.get("next_payment_attempt"))
    return reshaped


# ── Versioned serializers (payment-method plan reads) ─────────────────────────


class PaymentPlanSerializerV1(PaymentPlanSerializer):
    """v1 READ shape for payment-method plans (the ``manage_plans`` GET).

    ``PaymentPlanSerializer`` is the writable serializer used for both the GET
    (list) and the create/update of a plan. This subclass is selected ONLY on
    the read path; the write path keeps the v0 serializer byte-identical.

    Reshapes ``amount`` (a MAJOR-unit ``Decimal`` — the same value the Stripe
    adapter multiplies up to cents) into a C1 money object carrying the plan's
    own ``currency`` column. ``currency`` stays a sibling string; every other
    field (``interval``, ``recipient_id`` UUID strings, etc.) is unchanged.
    """

    amount = serializers.SerializerMethodField()

    class Meta(PaymentPlanSerializer.Meta):
        pass

    def get_amount(self, obj):
        return build_money_v1(getattr(obj, "amount", None), getattr(obj, "currency", None))


class PublicPaymentPlanSerializerV1(PublicPaymentPlanSerializer):
    """v1 READ shape for the public plan rows nested under a public method.

    Same major-unit ``amount`` -> C1 money reshape as
    :class:`PaymentPlanSerializerV1`; ``currency`` stays a sibling string.
    """

    amount = serializers.SerializerMethodField()

    class Meta(PublicPaymentPlanSerializer.Meta):
        pass

    def get_amount(self, obj):
        return build_money_v1(getattr(obj, "amount", None), getattr(obj, "currency", None))


class PublicPaymentMethodSerializerV1(PublicPaymentMethodSerializer):
    """v1 READ shape for the public workspace payment-method listing.

    The method row itself carries no money — only its nested ``plans`` do. This
    subclass re-renders ``plans`` through :class:`PublicPaymentPlanSerializerV1`
    so each plan's ``amount`` becomes a C1 money object. The plan-filter logic
    (context / recipient narrowing) is reused verbatim from the v0 parent.
    """

    plans = serializers.SerializerMethodField()

    class Meta(PublicPaymentMethodSerializer.Meta):
        pass

    def get_plans(self, obj):
        filters = self.context.get("plan_filters", {})
        context_key = filters.get("context")
        recipient_id = filters.get("recipient_id")
        if not context_key:
            return []

        qs = obj.plans.filter(context=context_key, is_active=True)
        if recipient_id:
            recipient_plans = qs.filter(recipient_id=recipient_id)
            qs = recipient_plans if recipient_plans.exists() else qs.filter(recipient__isnull=True)
        else:
            qs = qs.filter(recipient__isnull=True)

        qs = qs.order_by("sort_order", "created_at")
        return PublicPaymentPlanSerializerV1(qs, many=True).data


# ── Version selectors ─────────────────────────────────────────────────────────


def payment_plan_serializer_for_version(version):
    """Pick the payment-method plan serializer for the resolved API version.

    Returns the v1 read serializer only for ``v1``; v0 (and any write method)
    falls through to the writable ``PaymentPlanSerializer``.
    """
    return PaymentPlanSerializerV1 if version == "v1" else PaymentPlanSerializer


def public_payment_method_serializer_for_version(version):
    """Pick the public payment-method serializer for the resolved API version."""
    return (
        PublicPaymentMethodSerializerV1 if version == "v1" else PublicPaymentMethodSerializer
    )

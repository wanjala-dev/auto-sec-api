"""Stripe invoice shape utilities.

Stripe moved the subscription id off the top-level ``invoice.subscription``
field into a nested ``invoice.parent.subscription_details.subscription``
location in newer API responses, and again into
``invoice.lines.data[0].parent.subscription_item_details.subscription`` on
the line-item level. Code that still read the legacy top-level field
silently received ``None``, which broke subscription dedup keys and
produced duplicate Donation rows on subscription-mode checkouts.

This helper walks the known field locations in priority order and returns
the first match, so all webhook handlers stay aligned with Stripe's
current payload shape without sprinkling the same fallback across every
call site.
"""
from __future__ import annotations

from typing import Any, Mapping


def resolve_invoice_subscription_id(invoice: Mapping[str, Any] | None) -> str | None:
    """Return the subscription id for an invoice, regardless of payload version.

    Tries (in order):
      1. ``invoice.subscription`` — legacy / older API responses.
      2. ``invoice.subscription_details.subscription`` — middle generation.
      3. ``invoice.parent.subscription_details.subscription`` — current
         top-level location (2025+ API versions).
      4. ``invoice.lines.data[0].parent.subscription_item_details.subscription``
         — line-item-level fallback.
    """
    if not invoice or not isinstance(invoice, Mapping):
        return None

    direct = invoice.get("subscription")
    if direct:
        return _as_str(direct)

    details = invoice.get("subscription_details")
    if isinstance(details, Mapping):
        sub = details.get("subscription")
        if sub:
            return _as_str(sub)

    parent = invoice.get("parent")
    if isinstance(parent, Mapping):
        parent_details = parent.get("subscription_details")
        if isinstance(parent_details, Mapping):
            sub = parent_details.get("subscription")
            if sub:
                return _as_str(sub)

    lines = invoice.get("lines")
    if isinstance(lines, Mapping):
        line_data = lines.get("data") or []
        if isinstance(line_data, list) and line_data:
            first_line = line_data[0]
            if isinstance(first_line, Mapping):
                line_sub = first_line.get("subscription")
                if line_sub:
                    return _as_str(line_sub)
                line_parent = first_line.get("parent")
                if isinstance(line_parent, Mapping):
                    sub_item_details = line_parent.get("subscription_item_details")
                    if isinstance(sub_item_details, Mapping):
                        sub = sub_item_details.get("subscription")
                        if sub:
                            return _as_str(sub)

    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)

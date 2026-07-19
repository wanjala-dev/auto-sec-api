"""Resolver coverage for the Stripe invoice payload-shape shift."""

import pytest

from components.payments.infrastructure.services.stripe_invoice_helpers import (
    resolve_invoice_subscription_id,
)


def test_resolves_legacy_top_level_subscription_field():
    assert (
        resolve_invoice_subscription_id({"subscription": "sub_legacy"})
        == "sub_legacy"
    )


def test_resolves_top_level_subscription_details():
    assert (
        resolve_invoice_subscription_id(
            {"subscription_details": {"subscription": "sub_middle"}}
        )
        == "sub_middle"
    )


def test_resolves_current_parent_subscription_details():
    # This is the case that bit us in prod — Stripe 2025+ payload shape.
    payload = {
        "subscription": None,
        "subscription_details": None,
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": "sub_current"},
        },
    }
    assert resolve_invoice_subscription_id(payload) == "sub_current"


def test_resolves_line_item_level_fallback():
    payload = {
        "subscription": None,
        "lines": {
            "data": [
                {
                    "parent": {
                        "subscription_item_details": {"subscription": "sub_line"}
                    }
                }
            ]
        },
    }
    assert resolve_invoice_subscription_id(payload) == "sub_line"


def test_returns_none_when_no_subscription_field_present():
    assert resolve_invoice_subscription_id({"id": "in_xyz"}) is None
    assert resolve_invoice_subscription_id(None) is None
    assert resolve_invoice_subscription_id({}) is None


def test_priority_top_level_wins_over_nested():
    payload = {
        "subscription": "sub_winner",
        "parent": {
            "subscription_details": {"subscription": "sub_loser"}
        },
    }
    assert resolve_invoice_subscription_id(payload) == "sub_winner"


def test_empty_string_subscription_is_treated_as_missing():
    payload = {
        "subscription": "",
        "parent": {
            "subscription_details": {"subscription": "sub_fallback"}
        },
    }
    assert resolve_invoice_subscription_id(payload) == "sub_fallback"

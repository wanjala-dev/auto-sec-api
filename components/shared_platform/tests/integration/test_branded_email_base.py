"""The transactional email templates extend the shared branded base and adopt
the brand colour handed to the send context.

Each of the three templates ``{% extends "email/base.html" %}``; the CTA
button uses ``{{ brand_primary }}`` instead of the old hardcoded Octopus green
(#10b981). The wanjala workspace brand kit was not ported into this fork, so
``resolve_brand_colors`` always yields the Octopus fallback — pinned below.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string

from components.shared_platform.infrastructure.services.pdf_brand_assets import (
    resolve_brand_colors,
)

pytestmark = [pytest.mark.django_db]

_BRAND = "#7C3AED"
_OLD_GREEN = "background-color:#10b981"
_FALLBACK_LIGHT = "#42B98F"


def _render(template: str, extra: dict) -> str:
    context = {"site_name": "Octopus", "brand_primary": _BRAND, **extra}
    return render_to_string(template, context)


class TestBrandedEmailBase:
    def test_recurring_payment_reminder_uses_brand_button(self):
        html = _render(
            "email/recurring_payment_reminder.html",
            {
                "donor_name": "Amara",
                "amount": "25.00",
                "currency": "usd",
                "billing_date": "2026-08-01",
                "context_label": "sponsorship",
                "recipient_name": "Amani",
                "workspace_name": "Zaylan",
                "manage_url": "https://app.example.com/donations",
            },
        )
        assert _BRAND in html
        assert _OLD_GREEN not in html

    def test_share_invitation_uses_brand_button(self):
        html = _render(
            "email/share_invitation.html",
            {
                "sharer_display_name": "Grace",
                "resource_name": "Q3 Budget",
                "resource_type_label": "Budget",
                "owner_workspace_name": "Zaylan",
                "role_label": "Edit",
                "accept_url": "https://app.example.com/share/invitation/abc",
                "has_account": False,
                "invited_email": "amara@example.com",
                "verification_code": "482913",
                "expiry_days": 30,
            },
        )
        assert _BRAND in html
        assert _OLD_GREEN not in html

    def test_share_resource_invite_uses_brand_button(self):
        html = _render(
            "email/share_resource_invite.html",
            {
                "sharer_display_name": "Grace",
                "resource_name": "Q3 Budget",
                "resource_type_label": "Budget",
                "owner_workspace_name": "Zaylan",
                "role_label": "View",
                "accept_url": "https://app.example.com/budget/1",
                "has_account": True,
            },
        )
        assert _BRAND in html
        assert _OLD_GREEN not in html

    def test_resolve_brand_colors_yields_octopus_fallback(self, workspace_factory):
        # The wanjala brand kit is not ported into this fork — every
        # workspace deterministically resolves to the Octopus fallback,
        # with no import attempt and no logged traceback.
        workspace = workspace_factory()

        colors = resolve_brand_colors(str(workspace.id))

        assert colors["primary_light"] == _FALLBACK_LIGHT
        assert colors == resolve_brand_colors(None)

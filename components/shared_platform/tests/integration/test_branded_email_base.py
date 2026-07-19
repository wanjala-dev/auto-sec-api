"""The transactional email templates extend the shared branded base and adopt
the workspace brand colour.

Each of the three templates now ``{% extends "email/base.html" %}``; the CTA
button uses ``{{ brand_primary }}`` instead of the old hardcoded Octopus green
(#10b981). When a workspace is themed and its brand is resolved into the send
context, the rendered HTML carries that brand and the old green is gone.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string

from components.shared_platform.infrastructure.services.pdf_brand_assets import (
    resolve_brand_colors,
)
from components.workspace.application.commands.update_workspace_theme_command import (
    UpdateWorkspaceThemeCommand,
)
from components.workspace.application.providers.workspace_theme_provider import (
    WorkspaceThemeProvider,
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

    def test_themed_workspace_resolves_valid_light_brand(self, workspace_factory):
        # The adapter's brand-injection path uses ``primary_light`` for the
        # (light-themed) email accent. A themed workspace resolves to a valid
        # hex that is NOT the Octopus fallback.
        workspace = workspace_factory()
        WorkspaceThemeProvider.build_update_use_case().execute(
            UpdateWorkspaceThemeCommand(workspace_id=workspace.id, brand_seed=_BRAND, mode="light")
        )

        light = resolve_brand_colors(workspace.id)["primary_light"]

        assert light.startswith("#")
        assert len(light) == 7  # "#RRGGBB"
        assert light != _FALLBACK_LIGHT

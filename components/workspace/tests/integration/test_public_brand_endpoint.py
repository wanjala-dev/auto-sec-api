"""End-to-end coverage for the public workspace brand endpoint.

`GET /workspaces/<id>/public/brand/` is the anonymous counterpart to the
admin-only `WorkspaceThemeView`. It lets a logged-out visitor's page paint
itself in the org's brand without a login — the gap that left every public
surface rendering in the default palette.

Load-bearing invariants:

1. The endpoint MUST work without authentication (a fresh browser on a shared
   link is anonymous). If it regresses to ``IsAuthenticated`` the public pages
   silently fall back to default colours.
2. It MUST return the same resolved token shape the authenticated bootstrap
   delivers (``{mode, logo_url, light, dark}``), so the frontend can feed it
   straight into ``applyWorkspaceTheme``.
3. An unthemed OR unknown workspace MUST still return a palette (the default),
   never an error — brand is decoration, and the page's own data fetch enforces
   existence.
"""

from __future__ import annotations

import uuid as _uuid

import pytest

from components.workspace.application.commands.update_workspace_theme_command import (
    UpdateWorkspaceThemeCommand,
)
from components.workspace.application.providers.workspace_theme_provider import (
    WorkspaceThemeProvider,
)
from components.workspace.domain.value_objects.ui_surface_palette import APP_SURFACE_PALETTES
from components.workspace.infrastructure.adapters.pure_python_color_space_adapter import (
    PurePythonColorSpaceAdapter,
)

pytestmark = [pytest.mark.django_db]

_DEFAULT_PRIMARY = "46 219 232"  # autosec cyan #2EDBE8


class TestWorkspacePublicBrand:
    def test_anonymous_visitor_gets_default_palette_for_unthemed_workspace(self, api_client, workspace_factory):
        # No force_authenticate — exactly a logged-out browser on a shared link.
        workspace = workspace_factory()

        response = api_client.get(f"/workspaces/{workspace.id}/public/brand/")

        assert response.status_code == 200, response.content
        data = response.data["data"]
        # Frozen legacy keys always present; brand-kit keys are additive-only.
        assert set(data.keys()) >= {"mode", "logo_url", "light", "dark"}
        assert set(data.keys()) == {
            "mode",
            "logo_url",
            "light",
            "dark",
            "logos",
            "fonts",
            "ui_accent",
        }
        # An unbranded workspace gets no derived accent — the app keeps its own
        # built-in tokens, so nothing changes for a workspace that never branded.
        assert data["ui_accent"] is None
        # Unthemed → the default brand, so the page always renders.
        assert data["light"]["primary"] == _DEFAULT_PRIMARY
        # Unthemed fonts → the default typography with a full fallback stack.
        assert data["fonts"]["heading"]["family"] == "Poppins"
        assert "sans-serif" in data["fonts"]["body"]["stack"]

    def test_returns_the_workspaces_resolved_brand_when_themed(self, api_client, workspace_factory):
        workspace = workspace_factory()
        WorkspaceThemeProvider.build_update_use_case().execute(
            UpdateWorkspaceThemeCommand(
                workspace_id=workspace.id,
                brand_seed="#1E3A8A",
                secondary_seed="#F59E0B",
                logo_url="https://cdn.example/logo.png",
                mode="light",
            )
        )

        response = api_client.get(f"/workspaces/{workspace.id}/public/brand/")

        assert response.status_code == 200, response.content
        data = response.data["data"]
        # The resolved palette reflects the org's seed, not the default.
        assert data["light"]["primary"] != _DEFAULT_PRIMARY
        assert data["logo_url"] == "https://cdn.example/logo.png"
        # CSS-channel shape ("R G B") the frontend injects as --primary.
        assert len(data["light"]["primary"].split()) == 3

    def test_a_dark_brand_ships_an_accent_that_is_legible_on_our_canvas(self, api_client, workspace_factory):
        """The API must never emit an unusable accent — whatever the customer picks.

        ``#345700`` is the colour that shipped at ~2:1 on the dark HUD before
        this guard. The endpoint now carries a derived, AA-guaranteed ``text``
        variant per theme alongside the untouched brand fill.
        """
        workspace = workspace_factory()
        WorkspaceThemeProvider.build_update_use_case().execute(
            UpdateWorkspaceThemeCommand(workspace_id=workspace.id, brand_seed="#345700")
        )
        color_space = PurePythonColorSpaceAdapter()

        response = api_client.get(f"/workspaces/{workspace.id}/public/brand/")

        accent = response.data["data"]["ui_accent"]
        assert accent is not None
        assert accent["source"] == "#345700"
        assert accent["dark"]["adjusted"] is True

        for palette in APP_SURFACE_PALETTES:
            channels = accent[palette.key]["text"]
            assert len(channels.split()) == 3, "CSS channel shape, like every other token"
            hex_color = "#%02X%02X%02X" % tuple(int(c) for c in channels.split())
            for surface in palette.surfaces:
                assert color_space.contrast_ratio(hex_color, surface) >= 4.5

    def test_unknown_workspace_returns_default_palette_not_404(self, api_client):
        # A brand is decoration; the entity's own data fetch enforces
        # existence. So a bogus id gets the default palette, not an error.
        response = api_client.get(f"/workspaces/{_uuid.uuid4()}/public/brand/")

        assert response.status_code == 200
        assert response.data["data"]["light"]["primary"] == _DEFAULT_PRIMARY

    def test_voice_never_leaks_onto_the_public_payload(self, api_client, workspace_factory):
        # Voice is internal editorial data on an AllowAny endpoint — it must
        # never appear here, in any key, under any theming state.
        workspace = workspace_factory()
        WorkspaceThemeProvider.build_update_use_case().execute(
            UpdateWorkspaceThemeCommand(
                workspace_id=workspace.id,
                brand_seed="#1E3A8A",
                voice_tone="warm",
                voice_guidelines="Internal: always cite the fall gala.",
            )
        )

        response = api_client.get(f"/workspaces/{workspace.id}/public/brand/")

        assert response.status_code == 200
        body = response.content.decode()
        assert "voice" not in body
        assert "fall gala" not in body

    def test_logo_variants_and_fonts_served_publicly(self, api_client, workspace_factory):
        from infrastructure.persistence.workspaces.theming.models import BrandFontOption

        BrandFontOption.objects.create(
            key="lora",
            label="Lora",
            category="both",
            css_stack="'Lora', Georgia, serif",
            google_family="Lora:wght@400;500",
        )
        workspace = workspace_factory()
        WorkspaceThemeProvider.build_update_use_case().execute(
            UpdateWorkspaceThemeCommand(
                workspace_id=workspace.id,
                logo_url="https://cdn.example/logo.png",
                logo_icon_url="https://cdn.example/icon.png",
                favicon_url="https://cdn.example/favicon.png",
                font_heading="lora",
            )
        )

        response = api_client.get(f"/workspaces/{workspace.id}/public/brand/")

        data = response.data["data"]
        assert data["logos"]["icon"] == "https://cdn.example/icon.png"
        assert data["logos"]["favicon"] == "https://cdn.example/favicon.png"
        assert data["fonts"]["heading"]["family"] == "Lora"
        assert data["fonts"]["heading"]["google_family"] == "Lora:wght@400;500"
        # Body font untouched → default.
        assert data["fonts"]["body"]["family"] == "Inter"

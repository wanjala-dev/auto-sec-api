"""Integration: resolve a workspace's brand end-to-end (DB -> token payload)."""

from __future__ import annotations

import pytest

from components.workspace.application.providers.brand_resolution_provider import (
    get_brand_resolution_provider,
)
from components.workspace.domain.value_objects.semantic_token_set import BrandOutputShape
from components.workspace.infrastructure.adapters.pure_python_color_space_adapter import (
    PurePythonColorSpaceAdapter,
)
from components.workspace.infrastructure.repositories.workspace_theme_repository import (
    WorkspaceThemeRepository,
)

_CS = PurePythonColorSpaceAdapter()


@pytest.mark.django_db
class TestWorkspaceBrandResolution:
    def test_default_when_unthemed(self, workspace_factory):
        workspace = workspace_factory()
        payload = get_brand_resolution_provider().port().resolve(workspace.id)

        assert payload["mode"] == "light"
        assert payload["logo_url"] == ""
        # Default brand (autosec cyan), CSS-channel shape.
        assert payload["light"]["primary"] == "46 219 232"  # #2EDBE8
        assert payload["dark"]["background"] == "29 31 47"  # #1D1F2F
        assert payload["light"]["radius"] == "0.5rem"

    def test_custom_seed_resolves_accessible_hex(self, workspace_factory):
        workspace = workspace_factory()
        WorkspaceThemeRepository().upsert(
            workspace.id,
            brand_seed="#1E3A8A",
            secondary_seed="#F59E0B",
            logo_url="https://cdn.example/logo.png",
            mode="light",
            radius="",
        )
        payload = get_brand_resolution_provider().port().resolve(workspace.id, BrandOutputShape.HEX)

        assert payload["logo_url"] == "https://cdn.example/logo.png"
        light = payload["light"]
        assert light["primary"].startswith("#")
        assert _CS.contrast_ratio(light["primary-foreground"], light["primary"]) >= 4.5
        assert _CS.contrast_ratio(light["secondary-foreground"], light["secondary"]) >= 4.5

    def test_css_channel_shape(self, workspace_factory):
        workspace = workspace_factory()
        WorkspaceThemeRepository().upsert(
            workspace.id,
            brand_seed="#3B82F6",
            secondary_seed="",
            logo_url="",
            mode="light",
            radius="",
        )
        payload = get_brand_resolution_provider().port().resolve(workspace.id, BrandOutputShape.CSS)

        parts = payload["light"]["primary"].split()
        assert len(parts) == 3 and all(p.isdigit() for p in parts)

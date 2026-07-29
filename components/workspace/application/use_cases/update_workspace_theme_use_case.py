"""Use case: an admin updates a workspace's brand kit.

Validates the seed is a real hex colour (via the ``BrandSeed`` value object)
and that any selected fonts exist in the catalog, persists the inputs, and
returns the stored inputs + the freshly resolved preview.
"""

from __future__ import annotations

from components.workspace.application.commands.update_workspace_theme_command import (
    UpdateWorkspaceThemeCommand,
)
from components.workspace.application.ports.brand_resolution_port import BrandResolutionPort
from components.workspace.application.ports.font_catalog_port import FontCatalogPort
from components.workspace.application.ports.workspace_theme_store_port import WorkspaceThemeStorePort
from components.workspace.domain.errors import UnknownBrandFontError
from components.workspace.domain.value_objects.brand_seed import BrandSeed
from components.workspace.domain.value_objects.semantic_token_set import BrandOutputShape


class UpdateWorkspaceThemeUseCase:
    def __init__(
        self,
        store: WorkspaceThemeStorePort,
        resolution: BrandResolutionPort,
        font_catalog: FontCatalogPort,
    ) -> None:
        self._store = store
        self._resolution = resolution
        self._fonts = font_catalog

    def execute(self, command: UpdateWorkspaceThemeCommand) -> dict:
        # Reject invalid hex before persisting (raises InvalidBrandSeedError).
        if command.brand_seed.strip():
            BrandSeed(primary=command.brand_seed, secondary=command.secondary_seed or None)

        # Reject unknown font keys ("" = default, always valid).
        for key in (command.font_heading, command.font_body):
            if key.strip() and self._fonts.find_by_key(key.strip()) is None:
                raise UnknownBrandFontError(f"Unknown brand font: {key!r}")

        self._store.upsert(
            command.workspace_id,
            brand_seed=command.brand_seed,
            secondary_seed=command.secondary_seed,
            logo_url=command.logo_url,
            mode=command.mode,
            radius="",
            login_branding_enabled=command.login_branding_enabled,
            logo_icon_url=command.logo_icon_url,
            logo_dark_url=command.logo_dark_url,
            favicon_url=command.favicon_url,
            font_heading=command.font_heading.strip(),
            font_body=command.font_body.strip(),
            voice_tone=command.voice_tone,
            voice_guidelines=command.voice_guidelines,
        )
        stored = self._store.find_by_workspace(command.workspace_id)
        return {
            "brand_seed": stored.brand_seed,
            "secondary_seed": stored.secondary_seed,
            "logo_url": stored.logo_url,
            "logo_icon_url": stored.logo_icon_url,
            "logo_dark_url": stored.logo_dark_url,
            "favicon_url": stored.favicon_url,
            "font_heading": stored.font_heading,
            "font_body": stored.font_body,
            "voice_tone": stored.voice_tone,
            "voice_guidelines": stored.voice_guidelines,
            "mode": stored.mode,
            "resolved": self._resolution.resolve(command.workspace_id, BrandOutputShape.CSS),
        }

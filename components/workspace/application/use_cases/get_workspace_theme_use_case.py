"""Use case: read a workspace's brand settings (stored inputs + resolved preview)."""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_resolution_port import BrandResolutionPort
from components.workspace.application.ports.workspace_theme_store_port import WorkspaceThemeStorePort
from components.workspace.domain.value_objects.semantic_token_set import BrandOutputShape


class GetWorkspaceThemeUseCase:
    def __init__(self, store: WorkspaceThemeStorePort, resolution: BrandResolutionPort) -> None:
        self._store = store
        self._resolution = resolution

    def execute(self, workspace_id: UUID) -> dict:
        stored = self._store.find_by_workspace(workspace_id)
        return {
            "brand_seed": stored.brand_seed if stored else "",
            "secondary_seed": stored.secondary_seed if stored else "",
            "logo_url": stored.logo_url if stored else "",
            "logo_icon_url": stored.logo_icon_url if stored else "",
            "logo_dark_url": stored.logo_dark_url if stored else "",
            "favicon_url": stored.favicon_url if stored else "",
            "font_heading": stored.font_heading if stored else "",
            "font_body": stored.font_body if stored else "",
            "voice_tone": stored.voice_tone if stored else "",
            "voice_guidelines": stored.voice_guidelines if stored else "",
            "mode": stored.mode if stored else "light",
            "resolved": self._resolution.resolve(workspace_id, BrandOutputShape.CSS),
        }

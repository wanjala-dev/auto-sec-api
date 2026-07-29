"""Mapper: ORM ``WorkspaceTheme`` -> ``StoredWorkspaceTheme`` DTO."""

from __future__ import annotations

from components.workspace.application.ports.workspace_theme_store_port import StoredWorkspaceTheme


def to_stored_theme(model) -> StoredWorkspaceTheme:
    return StoredWorkspaceTheme(
        brand_seed=model.brand_seed or "",
        secondary_seed=model.secondary_seed or "",
        logo_url=model.logo_url or "",
        mode=model.mode or "light",
        radius=model.radius or "",
        login_branding_enabled=bool(model.login_branding_enabled),
        logo_icon_url=model.logo_icon_url or "",
        logo_dark_url=model.logo_dark_url or "",
        favicon_url=model.favicon_url or "",
        font_heading=model.font_heading or "",
        font_body=model.font_body or "",
        voice_tone=model.voice_tone or "",
        voice_guidelines=model.voice_guidelines or "",
    )

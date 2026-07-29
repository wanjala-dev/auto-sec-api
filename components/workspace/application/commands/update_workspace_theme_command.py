"""Command DTO: an admin updates a workspace's brand kit (seeds / logos /
fonts / voice / mode)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UpdateWorkspaceThemeCommand:
    workspace_id: UUID
    brand_seed: str = ""
    secondary_seed: str = ""
    logo_url: str = ""
    mode: str = "light"
    login_branding_enabled: bool = False
    logo_icon_url: str = ""
    logo_dark_url: str = ""
    favicon_url: str = ""
    font_heading: str = ""
    font_body: str = ""
    voice_tone: str = ""
    voice_guidelines: str = ""

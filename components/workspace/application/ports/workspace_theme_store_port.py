"""Port: persistence of a workspace's brand seed(s) (outbound / driven)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StoredWorkspaceTheme:
    """The persisted brand inputs for a workspace (not the resolved palette)."""

    brand_seed: str
    secondary_seed: str
    logo_url: str
    mode: str
    radius: str
    login_branding_enabled: bool = False
    logo_icon_url: str = ""
    logo_dark_url: str = ""
    favicon_url: str = ""
    font_heading: str = ""
    font_body: str = ""
    voice_tone: str = ""
    voice_guidelines: str = ""


class WorkspaceThemeStorePort(ABC):
    @abstractmethod
    def find_by_workspace(self, workspace_id: UUID) -> StoredWorkspaceTheme | None: ...

    @abstractmethod
    def find_display_name(self, workspace_id: UUID) -> str | None:
        """Return the workspace's display name, or ``None`` if it doesn't exist."""

    @abstractmethod
    def upsert(
        self,
        workspace_id: UUID,
        *,
        brand_seed: str,
        secondary_seed: str,
        logo_url: str,
        mode: str,
        radius: str,
        login_branding_enabled: bool = False,
        logo_icon_url: str = "",
        logo_dark_url: str = "",
        favicon_url: str = "",
        font_heading: str = "",
        font_body: str = "",
        voice_tone: str = "",
        voice_guidelines: str = "",
    ) -> StoredWorkspaceTheme: ...

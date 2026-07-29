"""Repository: WorkspaceTheme persistence (implements WorkspaceThemeStorePort)."""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.workspace_theme_store_port import (
    StoredWorkspaceTheme,
    WorkspaceThemeStorePort,
)
from components.workspace.mappers.db.workspace_theme_mapper import to_stored_theme


class WorkspaceThemeRepository(WorkspaceThemeStorePort):
    def find_by_workspace(self, workspace_id: UUID) -> StoredWorkspaceTheme | None:
        from infrastructure.persistence.workspaces.theming.models import WorkspaceTheme

        obj = WorkspaceTheme.objects.filter(workspace_id=workspace_id).first()
        return to_stored_theme(obj) if obj else None

    def find_display_name(self, workspace_id: UUID) -> str | None:
        from infrastructure.persistence.workspaces.models import Workspace

        return Workspace.objects.filter(id=workspace_id).values_list("workspace_name", flat=True).first()

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
    ) -> StoredWorkspaceTheme:
        from infrastructure.persistence.workspaces.theming.models import WorkspaceTheme

        obj, _ = WorkspaceTheme.objects.update_or_create(
            workspace_id=workspace_id,
            defaults={
                "brand_seed": brand_seed or "",
                "secondary_seed": secondary_seed or "",
                "logo_url": logo_url or "",
                "mode": mode or WorkspaceTheme.Mode.LIGHT,
                "radius": radius or "",
                "login_branding_enabled": bool(login_branding_enabled),
                "logo_icon_url": logo_icon_url or "",
                "logo_dark_url": logo_dark_url or "",
                "favicon_url": favicon_url or "",
                "font_heading": font_heading or "",
                "font_body": font_body or "",
                "voice_tone": voice_tone or "",
                "voice_guidelines": voice_guidelines or "",
            },
        )
        return to_stored_theme(obj)

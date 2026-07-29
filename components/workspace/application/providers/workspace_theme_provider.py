"""Composition root for the admin brand-settings use cases."""

from __future__ import annotations

from components.workspace.application.providers.brand_resolution_provider import (
    get_brand_resolution_provider,
)
from components.workspace.application.use_cases.get_workspace_theme_use_case import (
    GetWorkspaceThemeUseCase,
)
from components.workspace.application.use_cases.update_workspace_theme_use_case import (
    UpdateWorkspaceThemeUseCase,
)
from components.workspace.infrastructure.repositories.brand_font_catalog_repository import (
    BrandFontCatalogRepository,
)
from components.workspace.infrastructure.repositories.workspace_theme_repository import (
    WorkspaceThemeRepository,
)


class WorkspaceThemeProvider:
    @staticmethod
    def build_get_use_case() -> GetWorkspaceThemeUseCase:
        return GetWorkspaceThemeUseCase(WorkspaceThemeRepository(), get_brand_resolution_provider().port())

    @staticmethod
    def build_update_use_case() -> UpdateWorkspaceThemeUseCase:
        return UpdateWorkspaceThemeUseCase(
            WorkspaceThemeRepository(),
            get_brand_resolution_provider().port(),
            BrandFontCatalogRepository(),
        )

    @staticmethod
    def build_font_catalog() -> BrandFontCatalogRepository:
        return BrandFontCatalogRepository()

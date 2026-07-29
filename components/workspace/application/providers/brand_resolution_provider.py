"""Composition root for brand resolution — wires the domain resolver + colour
adapter + theme repository into the published ``BrandResolutionPort``.

Other contexts (reports, content, notifications) and the identity bootstrap
payload obtain the port via ``get_brand_resolution_provider().port()``.
"""

from __future__ import annotations

from components.workspace.application.ports.brand_resolution_port import BrandResolutionPort
from components.workspace.application.use_cases.resolve_workspace_brand_use_case import (
    ResolveWorkspaceBrandUseCase,
)
from components.workspace.domain.policies.wcag_contrast_policy import WcagContrastPolicy
from components.workspace.domain.services.brand_resolution_service import BrandResolutionService
from components.workspace.infrastructure.adapters.pure_python_color_space_adapter import (
    PurePythonColorSpaceAdapter,
)
from components.workspace.infrastructure.repositories.brand_font_catalog_repository import (
    BrandFontCatalogRepository,
)
from components.workspace.infrastructure.repositories.workspace_theme_repository import (
    WorkspaceThemeRepository,
)


class BrandResolutionProvider:
    @staticmethod
    def port() -> BrandResolutionPort:
        color_space = PurePythonColorSpaceAdapter()
        service = BrandResolutionService(color_space, WcagContrastPolicy(color_space))
        return ResolveWorkspaceBrandUseCase(
            store=WorkspaceThemeRepository(),
            resolution_service=service,
            color_space=color_space,
            font_catalog=BrandFontCatalogRepository(),
        )


def get_brand_resolution_provider() -> BrandResolutionProvider:
    return BrandResolutionProvider()
